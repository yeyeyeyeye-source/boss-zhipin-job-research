"""Non-interactive entry point for a user-confirmed Codex Skill strategy."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .collector import Collector
from .db import DEFAULT_DB_PATH, Database
from .exporter import export_strategy_run
from .strategy_model import StrategySpec
from .strategy_runner import RunResult, StrategyRunner


def _legacy_export_adapter(export_fn):
    def export_for_run(database, strategy_id, run_id, output_dir):
        run = database.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        task_ids = [
            task["task_id"]
            for task in database.list_strategy_tasks(
                strategy_id, int(run["scan_cycle"]),
            )
        ]
        output_path = Path(export_fn(database, task_ids, output_dir))
        database.update_run(
            run_id,
            export_status="completed",
            output_path=str(output_path),
            export_error="",
        )
        database.update_strategy(
            strategy_id, latest_output_path=str(output_path),
        )
        return output_path

    return export_for_run


def run_strategy(
    database: Database,
    *,
    search_keyword: str,
    target_role: str,
    target_type: str,
    cities: list[str],
    output_dir: str | Path | None = None,
    salary_filter: str = "",
    experience_filter: str = "",
    degree_filter: str = "",
    refresh: bool = False,
    confirm_access_restored: bool = False,
    ai_only: bool = False,
    collector_factory=Collector,
    export_fn=None,
    runner_factory=StrategyRunner,
    heartbeat_interval: float = 10.0,
) -> RunResult:
    if refresh and ai_only:
        raise ValueError("--refresh 不能与 --ai-only 同时使用")
    spec = StrategySpec.create(
        search_keyword,
        target_role,
        target_type,
        cities,
        salary_filter=salary_filter,
        experience_filter=experience_filter,
        degree_filter=degree_filter,
    )
    runner_export = (
        export_strategy_run
        if export_fn is None
        else _legacy_export_adapter(export_fn)
    )
    runner = runner_factory(
        database,
        collector_factory=collector_factory,
        export_fn=runner_export,
        heartbeat_interval=heartbeat_interval,
    )
    return runner.execute(
        spec,
        output_dir=output_dir,
        refresh=refresh,
        confirm_access_restored=confirm_access_restored,
        ai_only=ai_only,
    )


def export_existing_run(
    database: Database,
    run_id: str,
    output_dir: str | Path | None = None,
) -> Path:
    run = database.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    return export_strategy_run(
        database, run["strategy_id"], run_id, output_dir,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="执行已由用户确认的 BOSS 岗位检索策略")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--keyword", required=True)
    run.add_argument("--target-role", required=True)
    run.add_argument("--target-type", choices=("exact_role", "domain_scope"), required=True)
    run.add_argument("--cities", nargs="+", required=True)
    run.add_argument("--db", default=str(DEFAULT_DB_PATH))
    run.add_argument("--output-dir", default="")
    run.add_argument("--salary-filter", default="")
    run.add_argument("--experience-filter", default="")
    run.add_argument("--degree-filter", default="")
    run.add_argument("--refresh", action="store_true")
    run.add_argument("--confirm-access-restored", action="store_true")
    run.add_argument("--ai-only", action="store_true")
    run.add_argument("--execute", action="store_true")
    export = subparsers.add_parser("export")
    export.add_argument("--run-id", required=True)
    export.add_argument("--db", default=str(DEFAULT_DB_PATH))
    export.add_argument("--output-dir", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run" and not args.execute:
        print("拒绝执行：必须先向用户展示方案并获得确认，再传入 --execute", file=sys.stderr)
        return 2
    try:
        database = Database(args.db)
        if args.command == "export":
            output_path = export_existing_run(
                database, args.run_id, args.output_dir or None,
            )
            run = database.get_run(args.run_id)
            task_ids = [
                task["task_id"]
                for task in database.list_strategy_tasks(
                    run["strategy_id"], int(run["scan_cycle"]),
                )
            ]
            result = RunResult(
                task_ids=task_ids,
                status=run["status"],
                output_path=output_path,
                strategy_id=run["strategy_id"],
                run_id=run["run_id"],
                run_number=int(run["run_number"]),
                request_used=int(run["request_used"]),
                reused_existing_result=True,
            )
        else:
            result = run_strategy(
                database,
                search_keyword=args.keyword,
                target_role=args.target_role,
                target_type=args.target_type,
                cities=args.cities,
                output_dir=args.output_dir or None,
                salary_filter=args.salary_filter,
                experience_filter=args.experience_filter,
                degree_filter=args.degree_filter,
                refresh=args.refresh,
                confirm_access_restored=args.confirm_access_restored,
                ai_only=args.ai_only,
            )
    except (
        KeyError, OSError, RuntimeError, TimeoutError, ValueError, sqlite3.Error,
    ) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "task_ids": result.task_ids,
        "strategy_id": result.strategy_id,
        "run_id": result.run_id,
        "run_number": result.run_number,
        "request_used": result.request_used,
        "status": result.status,
        "output_path": str(result.output_path or ""),
        "reused_existing_result": result.reused_existing_result,
    }, ensure_ascii=False))
    return 0 if result.output_path else 3


if __name__ == "__main__":
    raise SystemExit(main())
