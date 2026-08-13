"""Persistent multi-Run orchestration for confirmed Codex Skill strategies."""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .collector import Collector
from .db import Database, TERMINAL_TASK_STATUSES, utc_now
from .exporter import (
    EXPORT_FAILURE_EXCEPTIONS,
    export_strategy_run,
    freeze_strategy_run_snapshot,
)
from .request_budget import RequestBudgetExhausted, RunRequestBudget
from .strategy_model import StrategySpec


@dataclass(frozen=True)
class RunResult:
    task_ids: list[str]
    status: str
    output_path: Path | None
    strategy_id: str = ""
    run_id: str = ""
    run_number: int = 0
    request_used: int = 0
    reused_existing_result: bool = False


class StrategyRunner:
    def __init__(
        self,
        database: Database,
        *,
        collector_factory: Callable[[Database], Any] = Collector,
        export_fn: Callable[
            [Database, str, str, str | Path | None], Path
        ] = export_strategy_run,
        heartbeat_interval: float = 10.0,
    ):
        self.database = database
        self.collector_factory = collector_factory
        self.export_fn = export_fn
        self.heartbeat_interval = max(0.01, float(heartbeat_interval))

    def _collector(self, budget: RunRequestBudget):
        collector = self.collector_factory(self.database)
        collector.request_budget = budget
        return collector

    @contextmanager
    def _task_worker(
        self,
        task_id: str,
        run_id: str,
        run_token: str,
    ):
        task_token = uuid.uuid4().hex
        if not self.database.reserve_worker(task_id, task_token):
            raise RuntimeError(f"城市任务正在运行: {task_id}")
        heartbeat_stop = threading.Event()
        heartbeat_started = False

        def heartbeat_loop() -> None:
            while not heartbeat_stop.wait(self.heartbeat_interval):
                try:
                    if not self.database.heartbeat(task_id, task_token):
                        return
                    if not self.database.heartbeat_run(run_id, run_token):
                        return
                except (OSError, sqlite3.Error):
                    return

        heartbeat = threading.Thread(
            target=heartbeat_loop,
            name=f"boss-strategy-{task_id[:8]}",
            daemon=True,
        )
        try:
            self.database.attach_worker_pid(task_id, task_token, os.getpid())
            heartbeat.start()
            heartbeat_started = True
            yield task_token
        finally:
            heartbeat_stop.set()
            if heartbeat_started:
                heartbeat.join(timeout=2)
            self.database.release_worker(task_id, task_token)

    def _run_task(
        self,
        task_id: str,
        run_id: str,
        run_token: str,
        budget: RunRequestBudget,
    ) -> None:
        with self._task_worker(task_id, run_id, run_token) as task_token:
            self._collector(budget).run(task_id, task_token)

    def _drain_saved_ai(
        self,
        task_ids: list[str],
        run_id: str,
        run_token: str,
        budget: RunRequestBudget,
    ) -> bool:
        available = True
        for task_id in task_ids:
            if not self.database.next_jobs(task_id, "ai"):
                continue
            original_status = self.database.get_task(task_id)["status"]
            with self._task_worker(task_id, run_id, run_token) as task_token:
                try:
                    if not self._collector(budget).drain_ai(task_id, task_token):
                        available = False
                        break
                finally:
                    current = self.database.get_task(task_id)
                    if current is not None and current["status"] == "processing":
                        self.database.update_task(task_id, status=original_status)
        return available

    def _normalize_strategy_task(self, task_id: str) -> dict[str, Any]:
        task = self.database.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if (
            task["status"] == "incomplete"
            and int(task["list_next_page"]) > int(task["max_pages"])
        ):
            snapshot = self.database.snapshot(task_id)
            status = (
                "completed_with_errors"
                if snapshot["failed"] else "completed"
            )
            self.database.update_task(task_id, status=status)
            task = self.database.get_task(task_id)
        return task

    @staticmethod
    def _task_stop_status(task: dict[str, Any]) -> str | None:
        if task["status"] == "paused":
            return "paused"
        if task["status"] == "waiting_for_access":
            return "waiting_for_access"
        if task["status"] == "waiting_for_login":
            return "waiting_for_login"
        if task["status"] == "waiting_for_ai":
            return "waiting_for_ai"
        return None

    def execute(
        self,
        spec: StrategySpec,
        *,
        output_dir: str | Path | None = None,
        refresh: bool = False,
        confirm_access_restored: bool = False,
        ai_only: bool = False,
    ) -> RunResult:
        strategy = self.database.get_or_create_strategy(spec)
        strategy_id = strategy["strategy_id"]
        cycle = int(strategy["current_scan_cycle"])
        latest = self.database.get_latest_run(strategy_id)
        latest_full = self.database.get_latest_run(
            strategy_id, scope="full",
        )
        cycle_tasks = self.database.list_strategy_tasks(strategy_id, cycle)
        cycle_complete = self.database.strategy_cycle_complete(
            strategy_id, cycle,
        )
        if (
            not refresh
            and not ai_only
            and cycle_complete
            and (latest is None or latest["status"] != "running")
        ):
            if latest is not None:
                output_path = (
                    Path(latest["output_path"])
                    if latest["output_path"] else None
                )
                if output_path is None or not output_path.is_file():
                    output_path = self.export_fn(
                        self.database,
                        strategy_id,
                        latest["run_id"],
                        output_dir,
                    )
            else:
                output_path = (
                    Path(strategy["latest_output_path"])
                    if strategy["latest_output_path"] else None
                )
            return RunResult(
                task_ids=[
                    task["task_id"]
                    for task in self.database.list_strategy_tasks(
                        strategy_id, cycle,
                    )
                ],
                status=str(latest["status"] if latest else "completed"),
                output_path=output_path,
                strategy_id=strategy_id,
                run_id=str(latest["run_id"] if latest else ""),
                run_number=int(latest["run_number"] if latest else 0),
                request_used=int(latest["request_used"] if latest else 0),
                reused_existing_result=True,
            )
        if (
            latest_full is not None
            and latest_full["status"] == "waiting_for_access"
            and not confirm_access_restored
            and not ai_only
        ):
            output_path = (
                Path(latest_full["output_path"])
                if latest_full["output_path"] else None
            )
            if output_path is None or not output_path.is_file():
                output_path = self.export_fn(
                    self.database,
                    strategy_id,
                    latest_full["run_id"],
                    output_dir,
                )
            return RunResult(
                task_ids=[
                    task["task_id"]
                    for task in self.database.list_strategy_tasks(
                        strategy_id, cycle,
                    )
                ],
                status="waiting_for_access",
                output_path=output_path,
                strategy_id=strategy_id,
                run_id=latest_full["run_id"],
                run_number=int(latest_full["run_number"]),
                request_used=int(latest_full["request_used"]),
                reused_existing_result=True,
            )
        if refresh:
            if latest is not None and latest["status"] == "running":
                raise RuntimeError(
                    "当前 Run 尚未完成，不能刷新；请先按原模式恢复并收口"
                )
            if cycle_tasks and not cycle_complete:
                raise RuntimeError(
                    "当前扫描周期未完成，不能刷新；请先继续未完成任务"
                )
            if cycle_tasks:
                cycle = self.database.advance_strategy_cycle(strategy_id)
        run, resumed = self.database.create_or_resume_run(
            strategy_id,
            cycle,
            scope="ai_only" if ai_only else "full",
            request_limit=500,
        )
        if resumed:
            cycle = int(run["scan_cycle"])
            ai_only = run["scope"] == "ai_only"
        run_id = run["run_id"]
        task_ids = self.database.ensure_strategy_tasks(
            strategy_id, cycle, spec, first_run_id=run_id,
        )
        for task_id in task_ids:
            self.database.update_task(task_id, last_run_id=run_id)
            task = self.database.get_task(task_id)
            if resumed and task["status"] == "paused":
                self.database.update_task(
                    task_id,
                    pause_requested=0,
                    status="pending",
                    error_message="",
                )
        run_token = uuid.uuid4().hex
        if not self.database.reserve_run_worker(run_id, run_token):
            raise RuntimeError(f"策略 Run 正在运行: {run_id}")
        run_heartbeat_stop = threading.Event()
        run_heartbeat_started = False

        def run_heartbeat_loop() -> None:
            while not run_heartbeat_stop.wait(self.heartbeat_interval):
                try:
                    if not self.database.heartbeat_run(run_id, run_token):
                        return
                except (OSError, sqlite3.Error):
                    return

        run_heartbeat = threading.Thread(
            target=run_heartbeat_loop,
            name=f"boss-run-{run_id[:8]}",
            daemon=True,
        )
        controlled_status: str | None = None
        had_errors = False
        try:
            self.database.update_run(run_id, worker_pid=os.getpid())
            run_heartbeat.start()
            run_heartbeat_started = True
            budget = RunRequestBudget(self.database, run_id)
            if ai_only:
                ai_available = self._drain_saved_ai(
                    task_ids, run_id, run_token, budget,
                )
                controlled_status = (
                    "completed" if ai_available else "waiting_for_ai"
                )
            else:
                for task_id in task_ids:
                    task = self.database.get_task(task_id)
                    if task["status"] in TERMINAL_TASK_STATUSES:
                        had_errors = (
                            had_errors
                            or task["status"] == "completed_with_errors"
                        )
                        continue
                    if resumed:
                        stop_status = self._task_stop_status(task)
                        if stop_status is not None:
                            controlled_status = stop_status
                            break
                    try:
                        self._run_task(
                            task_id, run_id, run_token, budget,
                        )
                    except RequestBudgetExhausted:
                        self.database.update_task(
                            task_id,
                            status="incomplete",
                            current_job_id=None,
                        )
                        controlled_status = "budget_exhausted"
                        break
                    task = self._normalize_strategy_task(task_id)
                    stop_status = self._task_stop_status(task)
                    if stop_status is not None:
                        controlled_status = stop_status
                        break
                    if task["status"] == "completed_with_errors":
                        had_errors = True
                        continue
                    if task["status"] != "completed":
                        raise RuntimeError(
                            f"城市任务未达到可收口状态: {task_id}={task['status']}"
                        )
                if controlled_status is not None and controlled_status != "paused":
                    self._drain_saved_ai(
                        task_ids, run_id, run_token, budget,
                    )
                if controlled_status is None:
                    if not self.database.strategy_cycle_complete(
                        strategy_id, cycle,
                    ):
                        raise RuntimeError("所有城市返回后扫描周期仍未完成")
                    controlled_status = (
                        "completed_with_errors" if had_errors else "completed"
                    )
            if controlled_status == "paused":
                current = self.database.get_run(run_id)
                return RunResult(
                    task_ids=task_ids,
                    status="paused",
                    output_path=None,
                    strategy_id=strategy_id,
                    run_id=run_id,
                    run_number=int(current["run_number"]),
                    request_used=int(current["request_used"]),
                    reused_existing_result=False,
                )
            self.database.update_run(
                run_id,
                status=controlled_status,
                stop_reason=controlled_status,
                finished_at=utc_now(),
            )
            freeze_strategy_run_snapshot(
                self.database, strategy_id, run_id,
            )
            output_path = None
            try:
                output_path = self.export_fn(
                    self.database,
                    strategy_id,
                    run_id,
                    output_dir,
                )
            except EXPORT_FAILURE_EXCEPTIONS:
                output_path = None
            finished = self.database.get_run(run_id)
            return RunResult(
                task_ids=task_ids,
                status=controlled_status,
                output_path=output_path,
                strategy_id=strategy_id,
                run_id=run_id,
                run_number=int(finished["run_number"]),
                request_used=int(finished["request_used"]),
                reused_existing_result=False,
            )
        finally:
            run_heartbeat_stop.set()
            if run_heartbeat_started:
                run_heartbeat.join(timeout=2)
            self.database.release_run_worker(run_id, run_token)
