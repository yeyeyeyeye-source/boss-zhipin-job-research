"""UI-safe task controls and detached worker process launching."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from .db import Database, utc_now


RUN_MODE_LIMITS: dict[str, int | None] = {
    "10条验证": 10,
    "20条稳定性测试": 20,
    "50条扩容测试": 50,
    "100条批量测试": 100,
    "自定义数量": None,
}


def resolve_job_limit(run_mode: str, custom_jobs: int | None = None) -> int:
    if run_mode not in RUN_MODE_LIMITS:
        raise ValueError(f"未知运行模式: {run_mode}")
    fixed_limit = RUN_MODE_LIMITS[run_mode]
    limit = fixed_limit if fixed_limit is not None else int(custom_jobs or 0)
    if limit < 1:
        raise ValueError("自定义岗位数量必须大于 0")
    return limit


class TaskManager:
    def __init__(
        self,
        database: Database,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    ):
        self.database = database
        self.popen = popen
        self.log_dir = database.path.parent / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _spawn(self, task_id: str, token: str, ai_only: bool = False) -> subprocess.Popen:
        command = [
            sys.executable, "-m", "boss_app.worker", "--task-id", task_id,
            "--db", str(self.database.path), "--worker-token", token,
        ]
        if ai_only:
            command.append("--ai-only")
        worker_env = os.environ.copy()
        worker_env["PYTHONIOENCODING"] = "utf-8"
        worker_env["PYTHONUTF8"] = "1"
        kwargs: dict[str, Any] = {"env": worker_env}
        if platform.system() == "Windows":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        else:
            kwargs["start_new_session"] = True
        log_path = self.log_dir / f"task_{task_id}.log"
        with open(log_path, "a", encoding="utf-8") as log_file:
            return self.popen(command, stdout=log_file, stderr=log_file, **kwargs)

    def start(self, task_id: str, ai_only: bool = False) -> bool:
        self.database.recover_interrupted()
        if self.database.get_task(task_id) is None:
            raise KeyError(task_id)
        token = uuid.uuid4().hex
        if not self.database.reserve_worker(task_id, token):
            return False
        try:
            process = self._spawn(task_id, token, ai_only=ai_only)
        except (OSError, subprocess.SubprocessError):
            self.database.release_worker(task_id, token)
            raise
        self.database.attach_worker_pid(task_id, token, process.pid)
        return True

    def pause(self, task_id: str) -> None:
        self.database.update_task(task_id, pause_requested=1)

    def resume(self, task_id: str) -> bool:
        self.database.update_task(task_id, pause_requested=0, status="pending", error_message="")
        return self.start(task_id)

    def expand(
        self, task_id: str, *, max_jobs: int, max_pages: int, run_mode: str,
    ) -> bool:
        """Update a stopped task's target and resume from its saved jobs."""
        self.database.update_task_limits(
            task_id, max_jobs=max_jobs, max_pages=max_pages, run_mode=run_mode,
        )
        return self.resume(task_id)

    def retry_ai(self, task_id: str) -> bool:
        with self.database.connect() as connection:
            connection.execute(
                """UPDATE jobs SET ai_status='waiting_for_ai', ai_error='', updated_at=?
                WHERE task_id=? AND crawl_status='completed'
                AND ai_status NOT IN ('completed', 'irrelevant')""",
                (utc_now(), task_id),
            )
        self.database.update_task(task_id, pause_requested=0, status="pending", error_message="")
        return self.start(task_id, ai_only=True)

    def snapshot(self, task_id: str) -> dict[str, Any]:
        return self.database.snapshot(task_id)
