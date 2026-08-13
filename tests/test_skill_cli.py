import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from boss_app.db import Database


class _CompletingCollector:
    def __init__(self, database, events):
        self.database = database
        self.events = events

    def run(self, task_id, token):
        task = self.database.get_task(task_id)
        self.events.append((task["keyword"], task["city"], task["target_role"], task["target_type"]))
        self.database.update_task(
            task_id, status="completed", list_next_page=16,
        )


class SkillCliTests(unittest.TestCase):
    def test_confirmed_strategy_runs_cities_sequentially_with_high_internal_limit(self):
        from boss_app.cli import run_strategy

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "jobs.db")
            events = []
            exporter = mock.Mock(return_value=Path(directory) / "result.xlsx")

            result = run_strategy(
                database,
                search_keyword="新媒体运营",
                target_role="新媒体运营",
                target_type="exact_role",
                cities=["北京", "上海"],
                output_dir=directory,
                collector_factory=lambda db: _CompletingCollector(db, events),
                export_fn=exporter,
            )

            self.assertEqual(events, [
                ("新媒体运营", "北京", "新媒体运营", "exact_role"),
                ("新媒体运营", "上海", "新媒体运营", "exact_role"),
            ])
            tasks = [database.get_task(task_id) for task_id in result.task_ids]
            self.assertEqual([(task["max_pages"], task["max_jobs"]) for task in tasks], [(15, 450), (15, 450)])
            exporter.assert_called_once_with(database, result.task_ids, directory)
            self.assertEqual(result.output_path, Path(directory) / "result.xlsx")

    def test_confirmed_strategy_keeps_worker_lease_alive(self):
        from boss_app.cli import run_strategy

        class SlowCollector(_CompletingCollector):
            def run(self, task_id, token):
                time.sleep(0.05)
                super().run(task_id, token)

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "jobs.db")
            with mock.patch.object(database, "heartbeat", wraps=database.heartbeat) as heartbeat:
                run_strategy(
                    database,
                    search_keyword="新媒体运营",
                    target_role="新媒体运营",
                    target_type="exact_role",
                    cities=["北京"],
                    output_dir=directory,
                    collector_factory=lambda db: SlowCollector(db, []),
                    export_fn=mock.Mock(return_value=Path(directory) / "result.xlsx"),
                    heartbeat_interval=0.01,
                )

            self.assertGreaterEqual(heartbeat.call_count, 1)

    def test_heartbeat_setup_failure_releases_worker_lease(self):
        from boss_app.cli import run_strategy

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "jobs.db")
            with mock.patch.object(
                database, "attach_worker_pid", side_effect=OSError("attach failed"),
            ):
                with self.assertRaisesRegex(OSError, "attach failed"):
                    run_strategy(
                        database,
                        search_keyword="新媒体运营",
                        target_role="新媒体运营",
                        target_type="exact_role",
                        cities=["北京"],
                        output_dir=directory,
                        collector_factory=lambda db: _CompletingCollector(db, []),
                        export_fn=mock.Mock(),
                    )

            task = database.list_tasks()[0]
            self.assertIsNone(task["worker_token"])
            self.assertIsNone(task["worker_pid"])
            self.assertIsNone(task["worker_heartbeat_at"])

    def test_access_restriction_stops_later_cities_and_still_exports_run(self):
        from boss_app.cli import run_strategy

        class RestrictedCollector(_CompletingCollector):
            def run(self, task_id, token):
                task = self.database.get_task(task_id)
                self.events.append(task["city"])
                self.database.update_task(task_id, status="waiting_for_access")

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "jobs.db")
            events = []
            expected = Path(directory) / "Run001.xlsx"
            exporter = mock.Mock(return_value=expected)

            result = run_strategy(
                database,
                search_keyword="AI产品",
                target_role="AI产品相关岗位",
                target_type="domain_scope",
                cities=["北京", "上海"],
                output_dir=directory,
                collector_factory=lambda db: RestrictedCollector(db, events),
                export_fn=exporter,
            )

            self.assertEqual(events, ["北京"])
            self.assertEqual(result.status, "waiting_for_access")
            self.assertEqual(result.output_path, expected)
            exporter.assert_called_once_with(database, result.task_ids, directory)

    def test_run_strategy_forwards_filters_and_lifecycle_flags(self):
        from boss_app.cli import run_strategy
        from boss_app.strategy_runner import RunResult

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "jobs.db")
            expected = RunResult(
                task_ids=[], status="completed",
                output_path=Path(directory) / "x.xlsx",
                strategy_id="strategy", run_id="run", run_number=2,
                request_used=17, reused_existing_result=False,
            )
            runner = mock.Mock()
            runner.execute.return_value = expected
            runner_factory = mock.Mock(return_value=runner)

            actual = run_strategy(
                database,
                search_keyword=" AI 运营 ",
                target_role="AI 运营",
                target_type="exact_role",
                cities=["北京", "上海"],
                salary_filter="405",
                experience_filter="104",
                degree_filter="203",
                output_dir=directory,
                refresh=True,
                confirm_access_restored=True,
                runner_factory=runner_factory,
            )

            self.assertIs(actual, expected)
            spec = runner.execute.call_args.args[0]
            self.assertEqual(spec.search_keyword, "AI 运营")
            self.assertEqual(spec.salary_filter, "405")
            self.assertEqual(spec.experience_filter, "104")
            self.assertEqual(spec.degree_filter, "203")
            runner.execute.assert_called_once_with(
                spec,
                output_dir=directory,
                refresh=True,
                confirm_access_restored=True,
                ai_only=False,
            )

    def test_refresh_and_ai_only_cannot_be_combined(self):
        from boss_app.cli import run_strategy

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "jobs.db")
            with self.assertRaisesRegex(ValueError, "refresh.*ai-only"):
                run_strategy(
                    database,
                    search_keyword="AI运营",
                    target_role="AI运营",
                    target_type="exact_role",
                    cities=["北京"],
                    refresh=True,
                    ai_only=True,
                )

    def test_cli_forwards_refresh_and_access_confirmation(self):
        from boss_app.cli import main
        from boss_app.strategy_runner import RunResult

        with tempfile.TemporaryDirectory() as directory:
            expected = RunResult(
                task_ids=["task"], status="completed",
                output_path=Path(directory) / "Run002.xlsx",
                strategy_id="strategy", run_id="run", run_number=2,
                request_used=9, reused_existing_result=False,
            )
            with mock.patch(
                "boss_app.cli.run_strategy", return_value=expected,
            ) as run:
                code = main([
                    "run", "--keyword", "AI运营", "--target-role", "AI运营",
                    "--target-type", "exact_role", "--cities", "北京",
                    "--db", str(Path(directory) / "jobs.db"),
                    "--refresh", "--confirm-access-restored", "--execute",
                ])

            self.assertEqual(code, 0)
            self.assertTrue(run.call_args.kwargs["refresh"])
            self.assertTrue(run.call_args.kwargs["confirm_access_restored"])
            self.assertFalse(run.call_args.kwargs["ai_only"])

    def test_pure_export_reuses_run_and_never_constructs_runner(self):
        from boss_app.cli import main
        from boss_app.strategy_model import StrategySpec

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "jobs.db"
            database = Database(db_path)
            spec = StrategySpec.create(
                "AI运营", "AI运营", "exact_role", ["北京"],
            )
            strategy = database.get_or_create_strategy(spec)
            run, _ = database.create_or_resume_run(
                strategy["strategy_id"], 1,
            )
            database.update_run(
                run["run_id"], status="completed", export_status="failed",
            )
            expected = Path(directory) / "recovered.xlsx"
            before = database.list_runs(strategy["strategy_id"])

            with mock.patch(
                "boss_app.cli.export_strategy_run", return_value=expected,
            ) as exporter, mock.patch("boss_app.cli.StrategyRunner") as runner:
                code = main([
                    "export", "--run-id", run["run_id"],
                    "--db", str(db_path), "--output-dir", directory,
                ])

            self.assertEqual(code, 0)
            exporter.assert_called_once()
            runner.assert_not_called()
            self.assertEqual(
                database.list_runs(strategy["strategy_id"]), before,
            )

    def test_pure_export_repairs_latest_pointer_for_an_existing_file(self):
        from boss_app.cli import export_existing_run
        from boss_app.strategy_model import StrategySpec

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "jobs.db")
            spec = StrategySpec.create(
                "AI运营", "AI运营", "exact_role", ["北京"],
            )
            strategy = database.get_or_create_strategy(spec)
            run, _ = database.create_or_resume_run(
                strategy["strategy_id"], 1,
            )
            output = Path(directory) / "Run001.xlsx"
            output.touch()
            database.update_run(
                run["run_id"],
                status="completed",
                export_status="completed",
                output_path=str(output),
            )

            recovered = export_existing_run(database, run["run_id"])

            self.assertEqual(recovered, output)
            self.assertEqual(
                database.get_strategy(strategy["strategy_id"])[
                    "latest_output_path"
                ],
                str(output),
            )

    def test_pure_export_refuses_a_running_run(self):
        from boss_app.cli import export_existing_run
        from boss_app.strategy_model import StrategySpec

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "jobs.db")
            spec = StrategySpec.create(
                "AI运营", "AI运营", "exact_role", ["北京"],
            )
            strategy = database.get_or_create_strategy(spec)
            run, _ = database.create_or_resume_run(
                strategy["strategy_id"], 1,
            )

            with self.assertRaisesRegex(RuntimeError, "running"):
                export_existing_run(database, run["run_id"], directory)

    def test_cli_requires_explicit_execute_flag(self):
        from boss_app.cli import main

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("boss_app.cli.Database") as database:
                code = main([
                    "run", "--keyword", "新媒体运营", "--target-role", "新媒体运营",
                    "--target-type", "exact_role", "--cities", "北京",
                    "--db", str(Path(directory) / "jobs.db"),
                ])

            self.assertEqual(code, 2)
            database.assert_not_called()
            self.assertFalse((Path(directory) / "jobs.db").exists())


class CodexSkillContractTests(unittest.TestCase):
    def test_skill_is_codex_first_and_requires_preview_confirmation(self):
        root = Path(__file__).resolve().parents[1]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = skill.split("---", 2)[1]

        self.assertIn("name: boss-zhipin-job-research", frontmatter)
        self.assertIn("description:", frontmatter)
        self.assertNotIn("metadata:", frontmatter)
        self.assertNotIn("platforms:", frontmatter)
        self.assertIn("已解析抓取方案", skill)
        self.assertIn("请确认是否按此方案执行", skill)
        self.assertIn("确认前不得访问 BOSS", skill)
        self.assertTrue((root / "agents" / "openai.yaml").is_file())

    def test_skill_documents_multi_run_budget_and_snapshot_contract(self):
        root = Path(__file__).resolve().parents[1]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")

        for expected in (
            "单次 Run 共用 500 次 BOSS 逻辑请求",
            "每个正常收口的 Run 都生成独立累计 Excel",
            "相同且已完成的策略默认直接返回最新 Excel",
            "--refresh",
            "--ai-only",
            "--confirm-access-restored",
        ):
            self.assertIn(expected, skill)


if __name__ == "__main__":
    unittest.main()
