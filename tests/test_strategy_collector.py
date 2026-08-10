import tempfile
import unittest
from pathlib import Path
from unittest import mock

from boss_app.ai_parser import AIConfig, JDParser, TargetParsedJD
from boss_app.collector import Collector
from boss_app.db import Database
from boss_app.login_manager import LoginState, LoginStatus
from boss_app.request_budget import RequestBudgetExhausted
from boss_app.strategy_model import StrategySpec


class _ConfiguredParser(JDParser):
    def __init__(self):
        super().__init__(AIConfig("key", "https://example.test", "model"))
        self.calls = 0

    def parse_target(self, full_jd, *, target_role, target_type, context=None):
        self.calls += 1
        return TargetParsedJD(
            match_status="matched",
            role_category=target_role,
            relevance_reason="完整 JD 与目标一致",
            relevance_confidence=0.95,
            job_type="全职",
            job_responsibilities=["职责"],
            job_requirements=["要求"],
            bonus_points=["无"],
        )


class _EventTargetParser(_ConfiguredParser):
    def __init__(self, events):
        super().__init__()
        self.events = events

    def parse_target(self, full_jd, *, target_role, target_type, context=None):
        self.events.append(f"ai:{context['job_name']}")
        return super().parse_target(
            full_jd,
            target_role=target_role,
            target_type=target_type,
            context=context,
        )


class StrategyCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.tempdir.name) / "jobs.db")
        self.spec = StrategySpec.create(
            "新媒体运营", "新媒体运营", "exact_role", ["北京", "上海"],
        )
        self.strategy = self.database.get_or_create_strategy(self.spec)
        self.run, _ = self.database.create_or_resume_run(
            self.strategy["strategy_id"], 1,
        )
        self.task_ids = self.database.ensure_strategy_tasks(
            self.strategy["strategy_id"], 1, self.spec,
            first_run_id=self.run["run_id"],
        )
        for task_id in self.task_ids:
            self.database.update_task(task_id, last_run_id=self.run["run_id"])

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _core_mock():
        from scripts import boss_cdp_raw as core

        core_module = mock.Mock()
        core_module.DetailLoginRequiredError = core.DetailLoginRequiredError
        core_module.DetailExtractionError = core.DetailExtractionError
        core_module.is_access_restriction_error.return_value = False
        return core_module

    def test_pre_request_detail_budget_stop_restores_pending_and_attempt_count(self):
        task_id = self.task_ids[0]
        self.database.upsert_job(task_id, {
            "job_id": "one", "encrypt_job_id": "source-one",
            "title": "岗位一",
            "job_link": "https://www.zhipin.com/job_detail/source-one.html",
        })
        token = "worker"
        self.assertTrue(self.database.reserve_worker(task_id, token))
        core_module = self._core_mock()
        core_module.fetch_job_detail.side_effect = RequestBudgetExhausted("500/500")
        collector = Collector(
            self.database, core_module=core_module,
            ai_parser=_ConfiguredParser(),
            sleep_fn=lambda _seconds: None, jitter_fn=lambda *_args: 0,
        )

        with self.assertRaises(RequestBudgetExhausted):
            collector._collect_details(task_id, token)

        row = self.database.list_jobs(task_id)[0]
        self.assertEqual(row["crawl_status"], "pending")
        self.assertEqual(row["crawl_attempts"], 0)

    def test_strategy_processes_page_details_before_requesting_next_page(self):
        task_id = self.task_ids[0]
        self.database.update_task_limits(
            task_id, max_jobs=4, max_pages=2, run_mode="pipeline-test",
        )
        token = "worker"
        self.assertTrue(self.database.reserve_worker(task_id, token))
        events = []
        core_module = self._core_mock()

        def list_pages(*_args, **kwargs):
            first_page = kwargs["start_page"]
            page_count = 1 if kwargs.get("page_limit") == 1 else 2
            for page in range(first_page, first_page + page_count):
                events.append(f"list:{page}")
                for index in (1, 2):
                    kwargs["on_job"]({
                        "job_id": f"p{page}-{index}",
                        "encrypt_job_id": f"source-p{page}-{index}",
                        "title": f"job p{page}-{index}",
                        "job_link": f"https://example.test/p{page}-{index}",
                    })
                kwargs["on_page_complete"](page + 1)
            return {"total": page_count * 2, "jobs": []}

        def fetch(job, **_kwargs):
            events.append(f"detail:{job['title']}")
            return {
                "title": job["title"], "location": "Beijing", "salary": "20-30K",
                "jd": "complete JD", "detail_url": job["job_link"],
            }

        core_module.scrape_list.side_effect = list_pages
        core_module.fetch_job_detail.side_effect = fetch
        collector = Collector(
            self.database,
            core_module=core_module,
            ai_parser=_EventTargetParser(events),
            sleep_fn=lambda _seconds: None,
            jitter_fn=lambda *_args: 0,
        )

        with mock.patch(
            "boss_app.collector.LoginManager.status",
            return_value=LoginState(LoginStatus.LOGGED_IN),
        ):
            collector.run(task_id, token)

        second_list = events.index("list:2")
        self.assertIn("detail:job p1-1", events[:second_list])
        self.assertIn("detail:job p1-2", events[:second_list])
        self.assertIn("ai:job p1-1", events[:second_list])
        self.assertIn("ai:job p1-2", events[:second_list])
        self.assertTrue(all(
            call.kwargs["page_limit"] == 1
            for call in core_module.scrape_list.call_args_list
        ))

    def test_complete_catalog_detail_is_not_fetched_again_in_second_city(self):
        job = {
            "job_id": "shared", "encrypt_job_id": "source-shared",
            "title": "同一岗位",
            "job_link": "https://www.zhipin.com/job_detail/source-shared.html",
        }
        self.database.upsert_job(self.task_ids[0], job)
        first = self.database.list_jobs(self.task_ids[0])[0]
        self.database.update_job(
            self.task_ids[0], first["job_id"],
            full_jd="完整 JD", crawl_status="completed", ai_status="completed",
        )
        self.database.upsert_job(self.task_ids[1], job)
        token = "worker"
        self.assertTrue(self.database.reserve_worker(self.task_ids[1], token))
        core_module = self._core_mock()
        collector = Collector(
            self.database, core_module=core_module,
            ai_parser=_ConfiguredParser(),
        )

        self.assertTrue(collector._collect_details(self.task_ids[1], token))

        core_module.fetch_job_detail.assert_not_called()

    def test_collector_forwards_one_budget_object_to_all_boss_paths(self):
        task_id = self.task_ids[0]
        budget = mock.Mock()
        core_module = self._core_mock()
        core_module.scrape_list.return_value = {"jobs": [], "total": 0}
        collector = Collector(
            self.database, core_module=core_module,
            ai_parser=_ConfiguredParser(), request_budget=budget,
        )
        token = "worker"
        self.assertTrue(self.database.reserve_worker(task_id, token))

        collector._collect_list(self.database.get_task(task_id), token)

        self.assertIs(
            core_module.scrape_list.call_args.kwargs["request_budget"], budget
        )

    def test_drain_ai_does_not_mark_an_unfinished_city_completed(self):
        task_id = self.task_ids[0]
        self.database.upsert_job(task_id, {
            "job_id": "one", "encrypt_job_id": "source-one",
            "title": "岗位一",
            "job_link": "https://www.zhipin.com/job_detail/source-one.html",
        })
        row = self.database.list_jobs(task_id)[0]
        self.database.update_job(
            task_id, row["job_id"], full_jd="完整 JD", crawl_status="completed",
        )
        token = "worker"
        self.assertTrue(self.database.reserve_worker(task_id, token))
        parser = _ConfiguredParser()
        collector = Collector(self.database, ai_parser=parser)

        self.assertTrue(collector.drain_ai(task_id, token))

        self.assertEqual(parser.calls, 1)
        self.assertEqual(self.database.get_task(task_id)["status"], "processing")
        self.assertEqual(
            self.database.list_jobs(task_id)[0]["ai_status"], "completed"
        )


if __name__ == "__main__":
    unittest.main()
