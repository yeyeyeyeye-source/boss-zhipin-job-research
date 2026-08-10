import tempfile
import threading
import unittest
from pathlib import Path

from boss_app.db import Database
from boss_app.request_budget import RequestBudgetExhausted, RunRequestBudget
from boss_app.strategy_model import StrategySpec


class RequestBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.tempdir.name) / "jobs.db")
        spec = StrategySpec.create("运营", "运营", "exact_role", ["北京"])
        self.strategy = self.database.get_or_create_strategy(spec)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_request_five_hundred_is_allowed_and_next_is_blocked(self):
        run, resumed = self.database.create_or_resume_run(
            self.strategy["strategy_id"], 1,
        )
        self.assertFalse(resumed)
        budget = RunRequestBudget(self.database, run["run_id"])

        for _ in range(500):
            budget.reserve("detail")
        with self.assertRaisesRegex(RequestBudgetExhausted, "500/500"):
            budget.reserve("list_page")

        self.assertEqual(self.database.get_run(run["run_id"])["request_used"], 500)

    def test_running_run_resumes_without_resetting_budget(self):
        first, _ = self.database.create_or_resume_run(
            self.strategy["strategy_id"], 1,
        )
        budget = RunRequestBudget(self.database, first["run_id"])
        for _ in range(17):
            budget.reserve("detail")

        resumed, was_resumed = self.database.create_or_resume_run(
            self.strategy["strategy_id"], 1,
        )

        self.assertTrue(was_resumed)
        self.assertEqual(resumed["run_id"], first["run_id"])
        self.assertEqual(resumed["request_used"], 17)

    def test_reserved_operation_remains_counted_when_operation_fails(self):
        run, _ = self.database.create_or_resume_run(
            self.strategy["strategy_id"], 1,
        )
        budget = RunRequestBudget(self.database, run["run_id"])

        budget.reserve("list_page")
        try:
            raise OSError("simulated network failure after reservation")
        except OSError:
            pass

        self.assertEqual(
            self.database.get_run(run["run_id"])["request_used"], 1,
        )

    def test_terminal_run_allows_next_explicit_run(self):
        first, _ = self.database.create_or_resume_run(
            self.strategy["strategy_id"], 1,
        )
        self.database.update_run(first["run_id"], status="budget_exhausted")

        second, resumed = self.database.create_or_resume_run(
            self.strategy["strategy_id"], 1,
        )

        self.assertFalse(resumed)
        self.assertEqual(second["run_number"], 2)
        self.assertEqual(second["request_used"], 0)

    def test_concurrent_reservations_cannot_exceed_limit(self):
        run, _ = self.database.create_or_resume_run(
            self.strategy["strategy_id"], 1, request_limit=5,
        )
        budget = RunRequestBudget(self.database, run["run_id"])
        barrier = threading.Barrier(10)
        outcomes = []

        def reserve():
            barrier.wait()
            try:
                budget.reserve("detail")
                outcomes.append("ok")
            except RequestBudgetExhausted:
                outcomes.append("blocked")

        threads = [threading.Thread(target=reserve) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(outcomes.count("ok"), 5)
        self.assertEqual(outcomes.count("blocked"), 5)
        self.assertEqual(self.database.get_run(run["run_id"])["request_used"], 5)

    def test_run_worker_lease_requires_stale_or_released_owner(self):
        run, _ = self.database.create_or_resume_run(
            self.strategy["strategy_id"], 1,
        )

        self.assertTrue(self.database.reserve_run_worker(run["run_id"], "one"))
        self.assertFalse(self.database.reserve_run_worker(run["run_id"], "two"))
        self.database.release_run_worker(run["run_id"], "one")
        self.assertTrue(self.database.reserve_run_worker(run["run_id"], "two"))


if __name__ == "__main__":
    unittest.main()
