"""Detached worker entry point for one SQLite-backed task."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import threading
import uuid

from .collector import Collector
from .db import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BOSS 本地采集任务 worker")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--worker-token", default="")
    parser.add_argument("--ai-only", action="store_true")
    args = parser.parse_args(argv)

    database = Database(args.db)
    token = args.worker_token or uuid.uuid4().hex
    task = database.get_task(args.task_id)
    if task is None:
        print(f"任务不存在: {args.task_id}", file=sys.stderr)
        return 2
    if args.worker_token:
        if task["worker_token"] != token:
            print("worker token 已失效", file=sys.stderr)
            return 3
    elif not database.reserve_worker(args.task_id, token):
        print("已有采集任务正在运行", file=sys.stderr)
        return 4
    database.attach_worker_pid(args.task_id, token, os.getpid())
    heartbeat_stop = threading.Event()

    def heartbeat_loop() -> None:
        while not heartbeat_stop.wait(10):
            try:
                if not database.heartbeat(args.task_id, token):
                    return
            except (OSError, sqlite3.Error):
                return

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        name=f"boss-heartbeat-{args.task_id[:8]}",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        Collector(database).run(args.task_id, token, ai_only=args.ai_only)
        return 0
    except (KeyError, OSError, RuntimeError, TimeoutError, ValueError, sqlite3.Error) as exc:
        database.update_task(args.task_id, status="failed", error_message=str(exc))
        print(f"任务失败: {exc}", file=sys.stderr)
        return 1
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2)
        database.release_worker(args.task_id, token)


if __name__ == "__main__":
    raise SystemExit(main())
