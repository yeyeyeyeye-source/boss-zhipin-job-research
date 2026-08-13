import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpyxl.utils.exceptions import InvalidFileException

from boss_app.db import Database
from boss_app.exporter import export_strategy_run
from boss_app.strategy_model import StrategySpec
from boss_app.strategy_runner import StrategyRunner


class _CompletingCollector:
    def __init__(self, database, events):
        self.database = database
        self.events = events
        self.request_budget = None

    def run(self, task_id, token):
        task = self.database.get_task(task_id)
        self.events.append(("run", task["city"], task["list_next_page"]))
        self.database.update_task(
            task_id, status="completed", list_next_page=16,
        )

    def drain_ai(self, task_id, token):
        self.events.append(("ai", self.database.get_task(task_id)["city"]))
        for job in self.database.next_jobs(task_id, "ai"):
            self.database.update_job(
                task_id,
                job["job_id"],
                ai_status="completed",
                job_responsibilities=["职责"],
                job_requirements=["要求"],
                bonus_points=["无"],
            )
        return True


class StrategyRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.directory = Path(self.tempdir.name)
        self.database = Database(self.directory / "jobs.db")
        self.spec = StrategySpec.create(
            "新媒体运营", "新媒体运营", "exact_role", ["北京", "上海"],
        )
        self.events = []
        self.exporter = mock.Mock(
            side_effect=self._export_file,
        )
        self.runner = StrategyRunner(
            self.database,
            collector_factory=lambda db: _CompletingCollector(db, self.events),
            export_fn=self.exporter,
            heartbeat_interval=0.01,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def _export_file(self, database, strategy_id, run_id, output_dir):
        run = database.get_run(run_id)
        path = self.directory / f"Run{run['run_number']:03d}.xlsx"
        path.touch()
        database.update_run(
            run_id, export_status="completed", output_path=str(path),
        )
        database.update_strategy(
            strategy_id, latest_output_path=str(path),
        )
        return path

    def test_full_run_processes_cities_in_order_and_exports_once(self):
        result = self.runner.execute(self.spec, output_dir=self.directory)

        self.assertEqual(
            [event[1] for event in self.events if event[0] == "run"],
            ["北京", "上海"],
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.run_number, 1)
        self.assertEqual(len(result.task_ids), 2)
        self.assertTrue(result.output_path.is_file())
        self.exporter.assert_called_once()

    def test_validation_failure_keeps_run_status_and_marks_export_failed(self):
        runner = StrategyRunner(
            self.database,
            collector_factory=lambda db: _CompletingCollector(db, self.events),
            export_fn=export_strategy_run,
            heartbeat_interval=0.01,
        )

        with mock.patch(
            "boss_app.exporter.load_workbook",
            side_effect=InvalidFileException("cannot verify"),
        ):
            result = runner.execute(self.spec, output_dir=self.directory)

        run = self.database.get_run(result.run_id)
        self.assertEqual(result.status, "completed")
        self.assertIsNone(result.output_path)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["export_status"], "failed")
        self.assertEqual(run["export_error"], "cannot verify")

    def test_programming_error_from_exporter_is_not_swallowed(self):
        runner = StrategyRunner(
            self.database,
            collector_factory=lambda db: _CompletingCollector(db, self.events),
            export_fn=mock.Mock(side_effect=AttributeError("programming bug")),
            heartbeat_interval=0.01,
        )

        with self.assertRaisesRegex(AttributeError, "programming bug"):
            runner.execute(self.spec, output_dir=self.directory)

    def test_run_and_task_leases_are_released(self):
        result = self.runner.execute(self.spec, output_dir=self.directory)

        run = self.database.get_run(result.run_id)
        self.assertIsNone(run["worker_token"])
        for task_id in result.task_ids:
            task = self.database.get_task(task_id)
            self.assertIsNone(task["worker_token"])
            self.assertIsNone(task["worker_pid"])

    def test_completed_with_errors_city_does_not_block_later_city(self):
        class ErrorCollector(_CompletingCollector):
            def run(self, task_id, token):
                task = self.database.get_task(task_id)
                self.events.append(("run", task["city"], task["list_next_page"]))
                status = (
                    "completed_with_errors"
                    if task["city"] == "北京" else "completed"
                )
                self.database.update_task(
                    task_id, status=status, list_next_page=16,
                )

        self.runner = StrategyRunner(
            self.database,
            collector_factory=lambda db: ErrorCollector(db, self.events),
            export_fn=self.exporter,
            heartbeat_interval=0.01,
        )

        result = self.runner.execute(self.spec, output_dir=self.directory)

        self.assertEqual(
            [event[1] for event in self.events if event[0] == "run"],
            ["北京", "上海"],
        )
        self.assertEqual(result.status, "completed_with_errors")

    def test_task_setup_failure_releases_task_and_run_leases(self):
        with mock.patch.object(
            self.database,
            "attach_worker_pid",
            side_effect=OSError("attach failed"),
        ):
            with self.assertRaisesRegex(OSError, "attach failed"):
                self.runner.execute(self.spec, output_dir=self.directory)

        task = self.database.list_tasks()[0]
        run = self.database.get_latest_run(task["strategy_id"])
        self.assertIsNone(task["worker_token"])
        self.assertIsNone(run["worker_token"])

    def test_budget_exhaustion_exports_then_next_run_resumes_same_task(self):
        class BudgetCollector(_CompletingCollector):
            shanghai_attempts = 0

            def run(self, task_id, token):
                task = self.database.get_task(task_id)
                self.events.append(("run", task["city"], task["list_next_page"]))
                if task["city"] == "北京":
                    for _ in range(300):
                        self.request_budget.reserve("detail")
                elif type(self).shanghai_attempts == 0:
                    type(self).shanghai_attempts += 1
                    self.database.update_task(task_id, list_next_page=6)
                    for _ in range(200):
                        self.request_budget.reserve("detail")
                    self.request_budget.reserve("detail")
                self.database.update_task(
                    task_id, status="completed", list_next_page=16,
                )

        runner = StrategyRunner(
            self.database,
            collector_factory=lambda db: BudgetCollector(db, self.events),
            export_fn=self.exporter,
            heartbeat_interval=0.01,
        )

        first = runner.execute(self.spec, output_dir=self.directory)
        second = runner.execute(self.spec, output_dir=self.directory)

        self.assertEqual(first.status, "budget_exhausted")
        self.assertEqual(first.request_used, 500)
        self.assertEqual(second.run_number, 2)
        self.assertEqual(second.request_used, 0)
        self.assertEqual(
            [event for event in self.events if event[0] == "run"][:3],
            [
                ("run", "北京", 1),
                ("run", "上海", 1),
                ("run", "上海", 6),
            ],
        )

    def test_existing_running_run_resumes_with_same_number_and_usage(self):
        strategy = self.database.get_or_create_strategy(self.spec)
        run, _ = self.database.create_or_resume_run(
            strategy["strategy_id"], 1,
        )
        for _ in range(17):
            self.database.reserve_run_request(run["run_id"])

        result = self.runner.execute(self.spec, output_dir=self.directory)

        self.assertEqual(result.run_id, run["run_id"])
        self.assertEqual(result.run_number, 1)
        self.assertEqual(result.request_used, 17)

    def test_paused_task_keeps_run_resumable_without_export(self):
        class PausingCollector(_CompletingCollector):
            def run(self, task_id, token):
                self.request_budget.reserve("detail")
                self.database.update_task(
                    task_id, status="paused", pause_requested=1,
                )

        runner = StrategyRunner(
            self.database,
            collector_factory=lambda db: PausingCollector(db, self.events),
            export_fn=self.exporter,
            heartbeat_interval=0.01,
        )

        result = runner.execute(self.spec, output_dir=self.directory)

        run = self.database.get_run(result.run_id)
        self.assertEqual(result.status, "paused")
        self.assertIsNone(result.output_path)
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["request_used"], 1)
        self.assertIsNone(run["finished_at"])
        self.assertFalse(run["export_rows_json"])
        self.assertIsNone(run["worker_token"])
        self.assertIsNone(self.database.get_task(result.task_ids[0])["worker_token"])
        self.exporter.assert_not_called()

    def test_paused_run_resumes_same_id_budget_and_clears_pause(self):
        class PauseOnceCollector(_CompletingCollector):
            attempts = 0

            def run(self, task_id, token):
                if type(self).attempts == 0:
                    type(self).attempts += 1
                    for _ in range(7):
                        self.request_budget.reserve("detail")
                    self.database.update_task(
                        task_id, status="paused", pause_requested=1,
                    )
                    return
                super().run(task_id, token)

        runner = StrategyRunner(
            self.database,
            collector_factory=lambda db: PauseOnceCollector(db, self.events),
            export_fn=self.exporter,
            heartbeat_interval=0.01,
        )

        first = runner.execute(self.spec, output_dir=self.directory)
        second = runner.execute(self.spec, output_dir=self.directory)

        self.assertEqual(first.status, "paused")
        self.assertEqual(second.status, "completed")
        self.assertEqual(second.run_id, first.run_id)
        self.assertEqual(second.run_number, first.run_number)
        self.assertEqual(second.request_used, 7)
        self.assertEqual(
            self.database.get_task(first.task_ids[0])["pause_requested"], 0,
        )

    def test_ai_only_rejects_a_running_full_run_without_boss_work(self):
        strategy = self.database.get_or_create_strategy(self.spec)
        run, _ = self.database.create_or_resume_run(
            strategy["strategy_id"], 1, scope="full",
        )

        with self.assertRaisesRegex(RuntimeError, "scope=full"):
            self.runner.execute(
                self.spec, output_dir=self.directory, ai_only=True,
            )

        current = self.database.get_run(run["run_id"])
        self.assertEqual(current["status"], "running")
        self.assertEqual(current["request_used"], 0)
        self.assertEqual(self.events, [])

    def test_refresh_rejects_an_unfinished_running_cycle_without_advancing(self):
        strategy = self.database.get_or_create_strategy(self.spec)
        run, _ = self.database.create_or_resume_run(
            strategy["strategy_id"], 1,
        )
        self.database.ensure_strategy_tasks(
            strategy["strategy_id"], 1, self.spec,
            first_run_id=run["run_id"],
        )

        with self.assertRaisesRegex(RuntimeError, "未完成.*刷新"):
            self.runner.execute(
                self.spec, output_dir=self.directory, refresh=True,
            )

        current = self.database.get_strategy(strategy["strategy_id"])
        self.assertEqual(current["current_scan_cycle"], 1)
        self.assertEqual(len(self.database.list_runs(strategy["strategy_id"])), 1)
        self.assertEqual(self.events, [])

    def test_running_run_with_completed_tasks_is_finalized_without_boss_work(self):
        strategy = self.database.get_or_create_strategy(self.spec)
        run, _ = self.database.create_or_resume_run(
            strategy["strategy_id"], 1,
        )
        task_ids = self.database.ensure_strategy_tasks(
            strategy["strategy_id"], 1, self.spec,
            first_run_id=run["run_id"],
        )
        for task_id in task_ids:
            self.database.update_task(
                task_id, status="completed", list_next_page=16,
            )

        result = self.runner.execute(self.spec, output_dir=self.directory)

        self.assertFalse(result.reused_existing_result)
        self.assertEqual(result.run_id, run["run_id"])
        self.assertEqual(result.status, "completed")
        self.assertEqual(
            self.database.get_run(run["run_id"])["status"], "completed",
        )
        self.assertEqual(self.events, [])

    def test_completed_identical_strategy_returns_latest_file_without_new_run(self):
        first = self.runner.execute(self.spec, output_dir=self.directory)
        event_count = len(self.events)
        export_count = self.exporter.call_count

        second = self.runner.execute(self.spec, output_dir=self.directory)

        self.assertTrue(second.reused_existing_result)
        self.assertEqual(second.run_id, first.run_id)
        self.assertEqual(second.output_path, first.output_path)
        self.assertEqual(len(self.events), event_count)
        self.assertEqual(self.exporter.call_count, export_count)

    def test_completed_strategy_prefers_latest_run_over_a_stale_pointer(self):
        first = self.runner.execute(self.spec, output_dir=self.directory)
        second = self.runner.execute(
            self.spec, output_dir=self.directory, refresh=True,
        )
        self.database.update_strategy(
            second.strategy_id, latest_output_path=str(first.output_path),
        )

        reused = self.runner.execute(self.spec, output_dir=self.directory)

        self.assertTrue(reused.reused_existing_result)
        self.assertEqual(reused.run_id, second.run_id)
        self.assertEqual(reused.output_path, second.output_path)

    def test_explicit_refresh_creates_new_cycle_tasks_from_page_one(self):
        first = self.runner.execute(self.spec, output_dir=self.directory)

        refreshed = self.runner.execute(
            self.spec, output_dir=self.directory, refresh=True,
        )

        self.assertEqual(refreshed.run_number, 2)
        self.assertNotEqual(first.task_ids, refreshed.task_ids)
        refreshed_tasks = [
            self.database.get_task(task_id) for task_id in refreshed.task_ids
        ]
        self.assertTrue(all(task["scan_cycle"] == 2 for task in refreshed_tasks))
        self.assertEqual(
            [event for event in self.events if event[0] == "run"][-2:],
            [("run", "北京", 1), ("run", "上海", 1)],
        )

    def test_access_stop_exports_and_requires_explicit_confirmation(self):
        class RestrictedCollector(_CompletingCollector):
            def run(self, task_id, token):
                task = self.database.get_task(task_id)
                self.events.append(("run", task["city"], task["list_next_page"]))
                self.database.update_task(
                    task_id, status="waiting_for_access",
                )

        runner = StrategyRunner(
            self.database,
            collector_factory=lambda db: RestrictedCollector(db, self.events),
            export_fn=self.exporter,
            heartbeat_interval=0.01,
        )
        first = runner.execute(self.spec, output_dir=self.directory)
        run_count = len(self.database.list_runs(first.strategy_id))
        blocked = runner.execute(self.spec, output_dir=self.directory)
        confirmed = self.runner.execute(
            self.spec,
            output_dir=self.directory,
            confirm_access_restored=True,
        )

        self.assertEqual(first.status, "waiting_for_access")
        self.assertTrue(first.output_path.is_file())
        self.assertTrue(blocked.reused_existing_result)
        self.assertEqual(blocked.run_id, first.run_id)
        self.assertEqual(confirmed.status, "completed")
        self.assertEqual(confirmed.run_number, 2)
        self.assertEqual(
            len(self.database.list_runs(first.strategy_id)), run_count + 1,
        )

    def test_ai_only_after_access_stop_does_not_clear_the_full_run_gate(self):
        class RestrictedCollector(_CompletingCollector):
            def run(self, task_id, token):
                task = self.database.get_task(task_id)
                self.events.append(("run", task["city"], task["list_next_page"]))
                self.database.update_task(
                    task_id, status="waiting_for_access",
                )

        restricted = StrategyRunner(
            self.database,
            collector_factory=lambda db: RestrictedCollector(db, self.events),
            export_fn=self.exporter,
            heartbeat_interval=0.01,
        )
        access_run = restricted.execute(
            self.spec, output_dir=self.directory,
        )
        ai_run = self.runner.execute(
            self.spec, output_dir=self.directory, ai_only=True,
        )
        event_count = len(self.events)
        run_count = len(self.database.list_runs(access_run.strategy_id))

        blocked = self.runner.execute(self.spec, output_dir=self.directory)

        self.assertEqual(access_run.status, "waiting_for_access")
        self.assertEqual(ai_run.status, "completed")
        self.assertEqual(ai_run.request_used, 0)
        self.assertTrue(blocked.reused_existing_result)
        self.assertEqual(blocked.status, "waiting_for_access")
        self.assertEqual(blocked.run_id, access_run.run_id)
        self.assertEqual(len(self.events), event_count)
        self.assertEqual(
            len(self.database.list_runs(access_run.strategy_id)), run_count,
        )

        confirmed = self.runner.execute(
            self.spec,
            output_dir=self.directory,
            confirm_access_restored=True,
        )
        self.assertEqual(confirmed.status, "completed")
        self.assertEqual(confirmed.run_number, 3)

    def test_ai_only_run_uses_zero_boss_requests(self):
        strategy = self.database.get_or_create_strategy(self.spec)
        bootstrap, _ = self.database.create_or_resume_run(
            strategy["strategy_id"], 1,
        )
        task_ids = self.database.ensure_strategy_tasks(
            strategy["strategy_id"], 1, self.spec,
            first_run_id=bootstrap["run_id"],
        )
        for index, task_id in enumerate(task_ids):
            self.database.upsert_job(task_id, {
                "job_id": f"ai-{index}",
                "encrypt_job_id": f"ai-source-{index}",
                "title": f"待 AI 岗位 {index}",
                "job_link": (
                    "https://www.zhipin.com/job_detail/"
                    f"ai-source-{index}.html"
                ),
            })
            row = self.database.list_jobs(task_id)[0]
            self.database.update_job(
                task_id,
                row["job_id"],
                full_jd="可供 AI 解析的完整 JD",
                crawl_status="completed",
            )
        self.database.update_run(bootstrap["run_id"], status="waiting_for_ai")

        result = self.runner.execute(
            self.spec, output_dir=self.directory, ai_only=True,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.request_used, 0)
        self.assertEqual(
            [event[0] for event in self.events],
            ["ai", "ai"],
        )

    def test_crash_resume_after_access_stop_finalizes_without_boss_work(self):
        strategy = self.database.get_or_create_strategy(self.spec)
        run, _ = self.database.create_or_resume_run(
            strategy["strategy_id"], 1,
        )
        task_ids = self.database.ensure_strategy_tasks(
            strategy["strategy_id"], 1, self.spec,
            first_run_id=run["run_id"],
        )
        self.database.update_task(
            task_ids[0], status="waiting_for_access",
        )

        result = self.runner.execute(self.spec, output_dir=self.directory)

        self.assertEqual(result.run_id, run["run_id"])
        self.assertEqual(result.status, "waiting_for_access")
        self.assertEqual(
            [event for event in self.events if event[0] == "run"], [],
        )


if __name__ == "__main__":
    unittest.main()
