import json
import tempfile
import unittest
from pathlib import Path

from boss_app.db import Database
from boss_app.strategy_model import StrategySpec


class StrategyDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.tempdir.name) / "jobs.db")
        self.spec = StrategySpec.create(
            "新媒体运营", "新媒体运营", "exact_role", ["北京", "上海"],
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_get_or_create_strategy_reuses_signature_and_updates_order(self):
        first = self.database.get_or_create_strategy(self.spec)
        reordered = StrategySpec.create(
            "新媒体运营", "新媒体运营", "exact_role", ["上海", "北京"],
        )
        second = self.database.get_or_create_strategy(reordered)

        self.assertEqual(first["strategy_id"], second["strategy_id"])
        self.assertEqual(json.loads(second["city_order_json"]), ["上海", "北京"])
        self.assertEqual(self.database.list_strategies(), [second])

    def test_strategy_tasks_are_unique_per_cycle_and_keep_fifteen_pages(self):
        strategy = self.database.get_or_create_strategy(self.spec)
        first = self.database.ensure_strategy_tasks(
            strategy["strategy_id"], 1, self.spec, first_run_id="run-one",
        )
        reordered = StrategySpec.create(
            "新媒体运营", "新媒体运营", "exact_role", ["上海", "北京"],
        )
        repeated = self.database.ensure_strategy_tasks(
            strategy["strategy_id"], 1, reordered, first_run_id="run-two",
        )

        self.assertEqual(set(first), set(repeated))
        self.assertEqual(repeated, [first[1], first[0]])
        tasks = self.database.list_strategy_tasks(strategy["strategy_id"], 1)
        self.assertEqual([task["city"] for task in tasks], ["上海", "北京"])
        self.assertEqual([task["city_order"] for task in tasks], [0, 1])
        self.assertTrue(all(task["max_pages"] == 15 for task in tasks))
        self.assertTrue(all(task["max_jobs"] == 450 for task in tasks))

    def test_refresh_cycle_creates_new_tasks_without_resetting_old_cursor(self):
        strategy = self.database.get_or_create_strategy(self.spec)
        old_ids = self.database.ensure_strategy_tasks(
            strategy["strategy_id"], 1, self.spec, first_run_id="run-one",
        )
        self.database.update_task(old_ids[0], list_next_page=9, status="completed")

        cycle = self.database.advance_strategy_cycle(strategy["strategy_id"])
        new_ids = self.database.ensure_strategy_tasks(
            strategy["strategy_id"], cycle, self.spec, first_run_id="run-two",
        )

        self.assertEqual(cycle, 2)
        self.assertNotEqual(old_ids, new_ids)
        self.assertEqual(self.database.get_task(old_ids[0])["list_next_page"], 9)
        self.assertTrue(
            all(self.database.get_task(item)["list_next_page"] == 1 for item in new_ids)
        )

    def test_legacy_task_remains_unassigned_and_unchanged(self):
        task_id = self.database.create_task("旧任务", "深圳")
        before = self.database.get_task(task_id)

        reopened = Database(self.database.path)
        after = reopened.get_task(task_id)

        self.assertEqual(after["strategy_id"], "")
        self.assertEqual(after["scan_cycle"], 0)
        self.assertEqual(after["keyword"], before["keyword"])
        self.assertEqual(after["city"], before["city"])

    def _strategy_tasks(self, spec=None):
        chosen = spec or self.spec
        strategy = self.database.get_or_create_strategy(chosen)
        run, _ = self.database.create_or_resume_run(
            strategy["strategy_id"], 1,
        )
        task_ids = self.database.ensure_strategy_tasks(
            strategy["strategy_id"], 1, chosen, first_run_id=run["run_id"],
        )
        for task_id in task_ids:
            self.database.update_task(task_id, last_run_id=run["run_id"])
        return strategy, run, task_ids

    def test_same_platform_job_has_one_catalog_row_across_city_tasks(self):
        strategy, run, task_ids = self._strategy_tasks()
        first = {
            "job_id": "beijing-local", "encrypt_job_id": "source-shared",
            "title": "同一岗位", "city_name": "北京",
            "job_link": "https://www.zhipin.com/job_detail/source-shared.html?lid=one",
        }
        second = {
            "job_id": "shanghai-local", "encrypt_job_id": "source-shared",
            "title": "同一岗位", "city_name": "上海",
            "job_link": "https://www.zhipin.com/job_detail/source-shared.html?lid=two",
        }

        self.assertTrue(self.database.upsert_job(task_ids[0], first))
        self.assertTrue(self.database.upsert_job(task_ids[1], second))

        self.assertEqual(self.database.count_catalog_jobs(), 1)
        self.assertEqual(len(self.database.list_jobs(task_ids[0])), 1)
        self.assertEqual(len(self.database.list_jobs(task_ids[1])), 1)
        self.assertEqual(
            self.database.list_jobs(task_ids[0])[0]["catalog_job_id"],
            self.database.list_jobs(task_ids[1])[0]["catalog_job_id"],
        )

    def test_complete_detail_is_reused_but_ai_is_strategy_specific(self):
        first_strategy, run, first_tasks = self._strategy_tasks()
        job = {
            "job_id": "shared", "encrypt_job_id": "source-shared",
            "title": "AI产品经理",
            "job_link": "https://www.zhipin.com/job_detail/source-shared.html",
        }
        self.database.upsert_job(first_tasks[0], job)
        first_row = self.database.list_jobs(first_tasks[0])[0]
        self.database.update_job(
            first_tasks[0], first_row["job_id"],
            full_jd="完整 JD", crawl_status="completed",
            ai_status="completed", job_responsibilities=["职责一"],
            job_requirements=["要求一"], bonus_points=["无"],
        )

        second_spec = StrategySpec.create(
            "AI产品", "AI产品经理", "exact_role", ["广州"],
        )
        second_strategy, second_run, second_tasks = self._strategy_tasks(second_spec)
        self.database.upsert_job(second_tasks[0], job)
        second_row = self.database.list_jobs(second_tasks[0])[0]

        self.assertEqual(self.database.count_catalog_jobs(), 1)
        self.assertEqual(second_row["crawl_status"], "completed")
        self.assertEqual(second_row["full_jd"], "完整 JD")
        self.assertEqual(second_row["ai_status"], "pending")
        self.assertNotEqual(first_strategy["strategy_id"], second_strategy["strategy_id"])

    def test_normalized_url_is_the_fallback_global_identity(self):
        strategy, run, task_ids = self._strategy_tasks()
        self.database.upsert_job(task_ids[0], {
            "job_id": "one", "title": "岗位",
            "job_link": "HTTPS://WWW.ZHIPIN.COM/job_detail/abc.html?lid=one#top",
        })
        self.database.upsert_job(task_ids[1], {
            "job_id": "two", "title": "岗位",
            "job_link": "https://www.zhipin.com/job_detail/abc.html/",
        })

        self.assertEqual(self.database.count_catalog_jobs(), 1)

    def test_source_and_url_collision_merges_rows_without_duplicate_task_links(self):
        strategy, run, task_ids = self._strategy_tasks()
        self.database.upsert_job(task_ids[0], {
            "job_id": "local-a", "encrypt_job_id": "source-a",
            "title": "岗位 A",
            "job_link": "https://www.zhipin.com/job_detail/a.html",
        })
        self.database.upsert_job(task_ids[1], {
            "job_id": "local-b", "encrypt_job_id": "source-b",
            "title": "岗位 B",
            "job_link": "https://www.zhipin.com/job_detail/b.html",
        })
        second = self.database.list_jobs(task_ids[1])[0]
        self.database.update_job(
            task_ids[1], second["job_id"],
            full_jd="这是应被保留的更长完整 JD",
            crawl_status="completed",
        )

        self.database.upsert_job(task_ids[0], {
            "job_id": "collision", "encrypt_job_id": "source-a",
            "title": "岗位 A 更新",
            "job_link": "https://www.zhipin.com/job_detail/b.html",
        })

        self.assertEqual(self.database.count_catalog_jobs(), 1)
        self.assertEqual(len(self.database.list_jobs(task_ids[0])), 1)
        self.assertEqual(len(self.database.list_jobs(task_ids[1])), 1)
        self.assertEqual(
            self.database.list_catalog_jobs()[0]["full_jd"],
            "这是应被保留的更长完整 JD",
        )

    def test_legacy_payload_is_backfilled_without_changing_legacy_row(self):
        legacy_task = self.database.create_task("历史岗位", "深圳")
        self.database.upsert_job(legacy_task, {
            "job_id": "legacy", "encrypt_job_id": "legacy-source",
            "title": "历史岗位",
            "job_link": "https://www.zhipin.com/job_detail/legacy-source.html",
        })
        self.database.update_job(
            legacy_task, "legacy", full_jd="历史完整 JD", crawl_status="completed",
        )
        before = self.database.list_jobs(legacy_task)[0]
        with self.database.connect() as connection:
            connection.execute("DELETE FROM job_catalog")
            connection.execute(
                "DELETE FROM app_state WHERE key='job_catalog_backfill_v1'"
            )

        reopened = Database(self.database.path)
        after = reopened.list_jobs(legacy_task)[0]
        catalog = reopened.list_catalog_jobs()

        self.assertEqual(after["job_id"], before["job_id"])
        self.assertEqual(after["full_jd"], before["full_jd"])
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["full_jd"], "历史完整 JD")


if __name__ == "__main__":
    unittest.main()
