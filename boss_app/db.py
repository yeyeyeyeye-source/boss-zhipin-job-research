"""SQLite persistence for resumable collection and AI processing tasks."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


DEFAULT_DB_PATH = Path.home() / ".boss-zhipin-scraper" / "boss_jobs.db"

TASK_STATUSES = {
    "pending", "processing", "paused", "completed", "completed_with_errors",
    "failed", "incomplete", "waiting_for_login", "waiting_for_ai",
    "waiting_for_access",
}
CRAWL_STATUSES = {"pending", "processing", "completed", "failed", "invalid", "waiting_for_login"}
AI_STATUSES = {
    "pending", "processing", "completed", "irrelevant", "failed", "invalid",
    "waiting_for_ai", "manual_review",
}
RUN_STATUSES = {
    "running", "budget_exhausted", "waiting_for_access", "waiting_for_login",
    "waiting_for_ai", "completed_with_errors", "completed",
}
RUN_SCOPES = {"full", "ai_only"}
EXPORT_STATUSES = {"pending", "completed", "failed"}
TERMINAL_TASK_STATUSES = {"completed", "completed_with_errors"}
CATALOG_UPDATE_FIELDS = {
    "job_name", "city", "salary_raw", "salary_range", "salary_months",
    "job_type", "experience", "education", "full_jd", "job_url",
    "normalized_job_url", "detail_url", "labels", "raw_json",
    "crawl_status", "crawl_attempts", "crawl_error", "error_message",
    "availability_status", "confirmed_unavailable_at",
}
STRATEGY_AI_UPDATE_FIELDS = {
    "ai_status", "ai_attempts", "ai_error", "error_message",
    "job_responsibilities", "job_requirements", "bonus_points",
    "role_category", "relevance_reason", "relevance_confidence",
}
AI_STATUS_RANK = {
    "pending": 0, "failed": 1, "waiting_for_ai": 1, "invalid": 2,
    "irrelevant": 3, "manual_review": 4, "completed": 5,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def normalize_job_url(value: str | None) -> str:
    """Return a stable job identity URL without tracking query/fragment data."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    path = "/".join(part for part in parsed.path.split("/") if part)
    path = f"/{path}" if path else ""
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def normalize_city_name(value: Any) -> str:
    """Keep only the city segment and discard finer-grained address data."""
    return str(value or "").split("·", 1)[0].strip(" ·")


def uses_qualified_target(keyword: Any, city: Any) -> bool:
    """Return whether a task target counts AI-qualified jobs, not candidates."""
    normalized_keyword = str(keyword or "").replace(" ", "").casefold()
    return normalized_keyword == "ai运营" and str(city or "").strip() == "全国"


def uses_ai_relevance_filter(keyword: Any, city: Any) -> bool:
    """Return whether a city task requires strict AI-product relevance."""
    normalized_keyword = "".join(str(keyword or "").lower().split())
    return normalized_keyword == "ai产品运营" and bool(str(city or "").strip())


def _ensure_column(
    connection: sqlite3.Connection, table: str, column: str, definition: str,
) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


class _ClosingConnection(sqlite3.Connection):
    """Commit/rollback and release Windows file handles on context exit."""

    def __exit__(self, exc_type, exc_value, traceback):
        result = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return result


class Database:
    """Small transactional data access layer with no ORM dependency."""

    def __init__(self, path: str | os.PathLike[str] = DEFAULT_DB_PATH):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    keyword TEXT NOT NULL,
                    city TEXT NOT NULL DEFAULT '',
                    salary_filter TEXT NOT NULL DEFAULT '',
                    experience_filter TEXT NOT NULL DEFAULT '',
                    degree_filter TEXT NOT NULL DEFAULT '',
                    max_pages INTEGER NOT NULL DEFAULT 1,
                    max_jobs INTEGER NOT NULL DEFAULT 10,
                    list_next_page INTEGER NOT NULL DEFAULT 1,
                    run_mode TEXT NOT NULL DEFAULT '10条验证',
                    target_role TEXT NOT NULL DEFAULT '',
                    target_type TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    pause_requested INTEGER NOT NULL DEFAULT 0,
                    worker_token TEXT,
                    worker_pid INTEGER,
                    worker_heartbeat_at TEXT,
                    current_job_id TEXT,
                    discovered_count INTEGER NOT NULL DEFAULT 0,
                    deduped_count INTEGER NOT NULL DEFAULT 0,
                    output_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    task_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    source_job_id TEXT NOT NULL DEFAULT '',
                    job_name TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    salary_raw TEXT NOT NULL DEFAULT '',
                    salary_range TEXT NOT NULL DEFAULT '未注明',
                    salary_months TEXT NOT NULL DEFAULT '未注明',
                    job_type TEXT NOT NULL DEFAULT '未注明',
                    experience TEXT NOT NULL DEFAULT '',
                    education TEXT NOT NULL DEFAULT '',
                    full_jd TEXT NOT NULL DEFAULT '',
                    job_responsibilities TEXT NOT NULL DEFAULT '待处理',
                    job_requirements TEXT NOT NULL DEFAULT '待处理',
                    bonus_points TEXT NOT NULL DEFAULT '待处理',
                    job_url TEXT NOT NULL DEFAULT '',
                    normalized_job_url TEXT NOT NULL DEFAULT '',
                    detail_url TEXT NOT NULL DEFAULT '',
                    labels TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    crawl_status TEXT NOT NULL DEFAULT 'pending',
                    ai_status TEXT NOT NULL DEFAULT 'pending',
                    crawl_attempts INTEGER NOT NULL DEFAULT 0,
                    ai_attempts INTEGER NOT NULL DEFAULT 0,
                    captured_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT NOT NULL DEFAULT '',
                    crawl_error TEXT NOT NULL DEFAULT '',
                    ai_error TEXT NOT NULL DEFAULT '',
                    role_category TEXT NOT NULL DEFAULT '',
                    relevance_reason TEXT NOT NULL DEFAULT '',
                    relevance_confidence REAL,
                    PRIMARY KEY (task_id, job_id),
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_crawl ON jobs(task_id, crawl_status);
                CREATE INDEX IF NOT EXISTS idx_jobs_ai ON jobs(task_id, ai_status);

                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategies (
                    strategy_id TEXT PRIMARY KEY,
                    signature TEXT NOT NULL UNIQUE,
                    search_keyword TEXT NOT NULL,
                    target_role TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    filters_json TEXT NOT NULL,
                    city_set_json TEXT NOT NULL,
                    city_order_json TEXT NOT NULL,
                    current_scan_cycle INTEGER NOT NULL DEFAULT 1,
                    latest_output_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategy_runs (
                    run_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    run_number INTEGER NOT NULL,
                    scan_cycle INTEGER NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'full',
                    request_limit INTEGER NOT NULL DEFAULT 500,
                    request_used INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'running',
                    stop_reason TEXT NOT NULL DEFAULT '',
                    export_status TEXT NOT NULL DEFAULT 'pending',
                    output_path TEXT NOT NULL DEFAULT '',
                    cumulative_export_count INTEGER NOT NULL DEFAULT 0,
                    export_rows_json TEXT NOT NULL DEFAULT '',
                    review_rows_json TEXT NOT NULL DEFAULT '',
                    export_snapshot_at TEXT,
                    worker_token TEXT,
                    worker_pid INTEGER,
                    worker_heartbeat_at TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    error_message TEXT NOT NULL DEFAULT '',
                    export_error TEXT NOT NULL DEFAULT '',
                    UNIQUE(strategy_id, run_number),
                    FOREIGN KEY(strategy_id) REFERENCES strategies(strategy_id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_strategy_runs_one_running
                ON strategy_runs(strategy_id) WHERE status='running';

                CREATE TABLE IF NOT EXISTS job_catalog (
                    catalog_job_id TEXT PRIMARY KEY,
                    source_job_id TEXT NOT NULL DEFAULT '',
                    job_name TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    salary_raw TEXT NOT NULL DEFAULT '',
                    salary_range TEXT NOT NULL DEFAULT '未注明',
                    salary_months TEXT NOT NULL DEFAULT '未注明',
                    job_type TEXT NOT NULL DEFAULT '未注明',
                    experience TEXT NOT NULL DEFAULT '',
                    education TEXT NOT NULL DEFAULT '',
                    full_jd TEXT NOT NULL DEFAULT '',
                    job_url TEXT NOT NULL DEFAULT '',
                    normalized_job_url TEXT NOT NULL DEFAULT '',
                    detail_url TEXT NOT NULL DEFAULT '',
                    labels TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    crawl_status TEXT NOT NULL DEFAULT 'pending',
                    crawl_attempts INTEGER NOT NULL DEFAULT 0,
                    crawl_error TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    availability_status TEXT NOT NULL DEFAULT 'available',
                    confirmed_unavailable_at TEXT,
                    first_captured_at TEXT NOT NULL,
                    last_updated_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_job_catalog_source
                ON job_catalog(source_job_id) WHERE source_job_id <> '';

                CREATE UNIQUE INDEX IF NOT EXISTS idx_job_catalog_url
                ON job_catalog(normalized_job_url) WHERE normalized_job_url <> '';

                CREATE TABLE IF NOT EXISTS strategy_jobs (
                    strategy_id TEXT NOT NULL,
                    catalog_job_id TEXT NOT NULL,
                    first_seen_run_id TEXT NOT NULL,
                    last_seen_run_id TEXT NOT NULL,
                    first_seen_task_id TEXT NOT NULL,
                    last_seen_task_id TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    ai_status TEXT NOT NULL DEFAULT 'pending',
                    ai_attempts INTEGER NOT NULL DEFAULT 0,
                    ai_error TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    job_responsibilities TEXT NOT NULL DEFAULT '待处理',
                    job_requirements TEXT NOT NULL DEFAULT '待处理',
                    bonus_points TEXT NOT NULL DEFAULT '待处理',
                    role_category TEXT NOT NULL DEFAULT '',
                    relevance_reason TEXT NOT NULL DEFAULT '',
                    relevance_confidence REAL,
                    PRIMARY KEY(strategy_id, catalog_job_id),
                    FOREIGN KEY(strategy_id) REFERENCES strategies(strategy_id),
                    FOREIGN KEY(catalog_job_id) REFERENCES job_catalog(catalog_job_id)
                );

                CREATE INDEX IF NOT EXISTS idx_strategy_jobs_ai
                ON strategy_jobs(strategy_id, ai_status);
                """
            )
            _ensure_column(
                connection, "tasks", "run_mode", "TEXT NOT NULL DEFAULT '10条验证'",
            )
            _ensure_column(
                connection, "tasks", "list_next_page", "INTEGER NOT NULL DEFAULT 1",
            )
            _ensure_column(
                connection, "jobs", "normalized_job_url", "TEXT NOT NULL DEFAULT ''",
            )
            _ensure_column(connection, "tasks", "target_role", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "tasks", "target_type", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "jobs", "role_category", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "jobs", "relevance_reason", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "jobs", "relevance_confidence", "REAL")
            _ensure_column(
                connection, "strategy_runs", "export_rows_json",
                "TEXT NOT NULL DEFAULT ''",
            )
            _ensure_column(
                connection, "strategy_runs", "review_rows_json",
                "TEXT NOT NULL DEFAULT ''",
            )
            _ensure_column(connection, "strategy_runs", "export_snapshot_at", "TEXT")
            _ensure_column(connection, "tasks", "strategy_id", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "tasks", "scan_cycle", "INTEGER NOT NULL DEFAULT 0")
            _ensure_column(connection, "tasks", "city_order", "INTEGER NOT NULL DEFAULT 0")
            _ensure_column(connection, "tasks", "first_run_id", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "tasks", "last_run_id", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "jobs", "catalog_job_id", "TEXT NOT NULL DEFAULT ''")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_strategy_cycle_city "
                "ON tasks(strategy_id, scan_cycle, city) WHERE strategy_id <> ''"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_catalog ON jobs(catalog_job_id)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_task_catalog_unique "
                "ON jobs(task_id, catalog_job_id) WHERE catalog_job_id <> ''"
            )
            rows = connection.execute(
                "SELECT task_id, job_id, job_url, normalized_job_url FROM jobs"
            ).fetchall()
            for row in rows:
                normalized = normalize_job_url(row["job_url"])
                if normalized != row["normalized_job_url"]:
                    connection.execute(
                        "UPDATE jobs SET normalized_job_url=? WHERE task_id=? AND job_id=?",
                        (normalized, row["task_id"], row["job_id"]),
                    )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_url "
                "ON jobs(task_id, normalized_job_url)"
            )
            if not connection.execute(
                "SELECT 1 FROM app_state WHERE key='job_catalog_backfill_v1'"
            ).fetchone():
                legacy_rows = connection.execute(
                    "SELECT * FROM jobs WHERE catalog_job_id=''"
                ).fetchall()
                for row in legacy_rows:
                    payload = dict(row)
                    try:
                        raw_payload = json.loads(payload.get("raw_json") or "{}")
                    except (json.JSONDecodeError, TypeError, ValueError):
                        raw_payload = {}
                    if isinstance(raw_payload, dict):
                        raw_payload.update(payload)
                    else:
                        raw_payload = payload
                    if raw_payload.get("source_job_id") or raw_payload.get("job_url"):
                        self._upsert_catalog_job(connection, raw_payload)
                connection.execute(
                    """INSERT INTO app_state(key, value, updated_at)
                    VALUES ('job_catalog_backfill_v1', 'complete', ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value, updated_at=excluded.updated_at""",
                    (utc_now(),),
                )

    def create_task(
        self,
        keyword: str,
        city: str = "",
        salary_filter: str = "",
        experience_filter: str = "",
        degree_filter: str = "",
        max_pages: int = 1,
        max_jobs: int = 10,
        run_mode: str = "10条验证",
        task_id: str | None = None,
        *,
        target_role: str = "",
        target_type: str = "",
        strategy_id: str = "",
        scan_cycle: int = 0,
        city_order: int = 0,
        first_run_id: str = "",
    ) -> str:
        keyword = str(keyword or "").strip()
        if not keyword:
            raise ValueError("岗位名称不能为空")
        target_role = str(target_role or "").strip()
        target_type = str(target_type or "").strip()
        if target_role and target_type not in {"exact_role", "domain_scope"}:
            raise ValueError("目标类型必须是 exact_role 或 domain_scope")
        if target_type and not target_role:
            raise ValueError("目标类型不能脱离目标岗位")
        strategy_id = str(strategy_id or "").strip()
        scan_cycle = max(0, int(scan_cycle))
        city_order = max(0, int(city_order))
        first_run_id = str(first_run_id or "").strip()
        last_run_id = first_run_id
        identifier = task_id or uuid.uuid4().hex
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO tasks (
                    task_id, keyword, city, salary_filter, experience_filter,
                    degree_filter, max_pages, max_jobs, run_mode, target_role,
                    target_type, strategy_id, scan_cycle, city_order, first_run_id,
                    last_run_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    identifier, keyword, str(city or "").strip(), salary_filter or "",
                    experience_filter or "", degree_filter or "", max(1, int(max_pages)),
                    max(1, int(max_jobs)), str(run_mode or "自定义数量"),
                    target_role, target_type, strategy_id, scan_cycle, city_order,
                    first_run_id, last_run_id, now, now,
                ),
            )
        return identifier

    def update_task_limits(
        self, task_id: str, *, max_jobs: int, max_pages: int, run_mode: str,
    ) -> None:
        """Expand a stopped historical task without replacing its saved jobs."""
        job_limit = int(max_jobs)
        page_limit = int(max_pages)
        if job_limit < 1 or page_limit < 1:
            raise ValueError("最大岗位数量和最大页数必须大于 0")
        with self.connect() as connection:
            task = connection.execute(
                "SELECT worker_token, keyword, city FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if task is None:
                raise KeyError(task_id)
            if task["worker_token"]:
                raise RuntimeError("任务正在运行，不能修改扩容参数")
            qualified_target = uses_qualified_target(task["keyword"], task["city"])
            minimum = connection.execute(
                (
                    "SELECT COUNT(*) FROM jobs WHERE task_id=? "
                    "AND crawl_status='completed' AND ai_status='completed'"
                    if qualified_target
                    else "SELECT COUNT(*) FROM jobs WHERE task_id=?"
                ),
                (task_id,),
            ).fetchone()[0]
            if job_limit < minimum:
                count_name = "合格岗位数" if qualified_target else "已有岗位数"
                raise ValueError(f"最大岗位数量不能小于{count_name} {minimum}")
            connection.execute(
                """UPDATE tasks SET max_jobs=?, max_pages=?, run_mode=?,
                updated_at=? WHERE task_id=?""",
                (job_limit, page_limit, str(run_mode), utc_now(), task_id),
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (max(1, int(limit)),)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_strategy(self, strategy_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategies WHERE strategy_id=?", (strategy_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_strategies(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM strategies ORDER BY created_at, strategy_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_or_create_strategy(self, spec) -> dict[str, Any]:
        now = utc_now()
        strategy_id = uuid.uuid4().hex
        filters_json = json.dumps(spec.filters, ensure_ascii=False, sort_keys=True)
        city_set_json = json.dumps(spec.city_set, ensure_ascii=False)
        city_order_json = json.dumps(spec.ordered_cities, ensure_ascii=False)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO strategies (
                    strategy_id, signature, search_keyword, target_role, target_type,
                    filters_json, city_set_json, city_order_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signature) DO UPDATE SET
                    city_order_json=excluded.city_order_json,
                    updated_at=excluded.updated_at""",
                (
                    strategy_id, spec.signature, spec.search_keyword, spec.target_role,
                    spec.target_type, filters_json, city_set_json, city_order_json,
                    now, now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM strategies WHERE signature=?", (spec.signature,),
            ).fetchone()
        return dict(row)

    def advance_strategy_cycle(self, strategy_id: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE strategies
                SET current_scan_cycle=current_scan_cycle + 1, updated_at=?
                WHERE strategy_id=?""",
                (utc_now(), strategy_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(strategy_id)
            row = connection.execute(
                "SELECT current_scan_cycle FROM strategies WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()
        return int(row["current_scan_cycle"])

    def ensure_strategy_tasks(
        self, strategy_id: str, scan_cycle: int, spec, *, first_run_id: str,
    ) -> list[str]:
        existing = {
            row["city"]: row["task_id"]
            for row in self.list_strategy_tasks(strategy_id, scan_cycle)
        }
        task_ids: list[str] = []
        for index, city in enumerate(spec.ordered_cities):
            task_id = existing.get(city)
            if task_id is None:
                task_id = self.create_task(
                    spec.search_keyword,
                    city,
                    salary_filter=spec.salary_filter,
                    experience_filter=spec.experience_filter,
                    degree_filter=spec.degree_filter,
                    max_pages=15,
                    max_jobs=450,
                    run_mode="Codex Skill 多轮深度检索",
                    target_role=spec.target_role,
                    target_type=spec.target_type,
                    strategy_id=strategy_id,
                    scan_cycle=scan_cycle,
                    city_order=index,
                    first_run_id=first_run_id,
                )
            else:
                self.update_task(task_id, city_order=index)
            task_ids.append(task_id)
        return task_ids

    def list_strategy_tasks(
        self, strategy_id: str, scan_cycle: int,
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM tasks
                WHERE strategy_id=? AND scan_cycle=?
                ORDER BY city_order, created_at, task_id""",
                (strategy_id, int(scan_cycle)),
            ).fetchall()
        return [dict(row) for row in rows]

    def strategy_cycle_complete(self, strategy_id: str, scan_cycle: int) -> bool:
        strategy = self.get_strategy(strategy_id)
        if strategy is None:
            raise KeyError(strategy_id)
        expected = len(json.loads(strategy["city_set_json"]))
        tasks = self.list_strategy_tasks(strategy_id, scan_cycle)
        return (
            len(tasks) == expected
            and all(task["status"] in TERMINAL_TASK_STATUSES for task in tasks)
        )

    def update_strategy(self, strategy_id: str, **fields: Any) -> None:
        allowed = {"latest_output_path", "city_order_json"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in updates)
        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE strategies SET {assignments} WHERE strategy_id=?",
                (*updates.values(), strategy_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(strategy_id)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategy_runs WHERE run_id=?", (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_latest_run(
        self, strategy_id: str, *, scope: str | None = None,
    ) -> dict[str, Any] | None:
        if scope is not None and scope not in RUN_SCOPES:
            raise ValueError(f"未知 Run 范围: {scope}")
        with self.connect() as connection:
            if scope is None:
                row = connection.execute(
                    """SELECT * FROM strategy_runs WHERE strategy_id=?
                    ORDER BY run_number DESC LIMIT 1""",
                    (strategy_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """SELECT * FROM strategy_runs
                    WHERE strategy_id=? AND scope=?
                    ORDER BY run_number DESC LIMIT 1""",
                    (strategy_id, scope),
                ).fetchone()
        return dict(row) if row else None

    def list_runs(self, strategy_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM strategy_runs WHERE strategy_id=?
                ORDER BY run_number""",
                (strategy_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_or_resume_run(
        self,
        strategy_id: str,
        scan_cycle: int,
        *,
        scope: str = "full",
        request_limit: int = 500,
    ) -> tuple[dict[str, Any], bool]:
        if scope not in RUN_SCOPES:
            raise ValueError(f"未知 Run 范围: {scope}")
        limit = int(request_limit)
        if limit < 1:
            raise ValueError("请求上限必须大于 0")
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """SELECT * FROM strategy_runs
                WHERE strategy_id=? AND status='running'
                ORDER BY run_number DESC LIMIT 1""",
                (strategy_id,),
            ).fetchone()
            if current is not None:
                if current["scope"] != scope:
                    raise RuntimeError(
                        "运行中的 Run "
                        f"scope={current['scope']}，不能按 scope={scope} 恢复"
                    )
                connection.commit()
                return dict(current), True
            number = int(connection.execute(
                "SELECT COALESCE(MAX(run_number), 0) + 1 "
                "FROM strategy_runs WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()[0])
            run_id = uuid.uuid4().hex
            now = utc_now()
            connection.execute(
                """INSERT INTO strategy_runs (
                    run_id, strategy_id, run_number, scan_cycle, scope,
                    request_limit, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, strategy_id, number, int(scan_cycle), scope, limit, now),
            )
            row = connection.execute(
                "SELECT * FROM strategy_runs WHERE run_id=?", (run_id,),
            ).fetchone()
            connection.commit()
            return dict(row), False
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {
            "status", "stop_reason", "export_status", "output_path",
            "cumulative_export_count", "finished_at", "error_message",
            "export_error", "worker_pid", "export_rows_json",
            "review_rows_json", "export_snapshot_at",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "status" in updates and updates["status"] not in RUN_STATUSES:
            raise ValueError(f"未知 Run 状态: {updates['status']}")
        if (
            "export_status" in updates
            and updates["export_status"] not in EXPORT_STATUSES
        ):
            raise ValueError(f"未知导出状态: {updates['export_status']}")
        if not updates:
            return
        assignments = ", ".join(f"{key}=?" for key in updates)
        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE strategy_runs SET {assignments} WHERE run_id=?",
                (*updates.values(), run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)

    def reserve_run_request(self, run_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE strategy_runs
                SET request_used=request_used + 1
                WHERE run_id=? AND status='running'
                  AND request_used < request_limit""",
                (run_id,),
            )
        return cursor.rowcount == 1

    def reserve_run_worker(
        self, run_id: str, token: str, stale_seconds: int = 60,
    ) -> bool:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
        ).isoformat()
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE strategy_runs
                SET worker_token=?, worker_heartbeat_at=?
                WHERE run_id=? AND status='running'
                  AND (
                    worker_token IS NULL
                    OR worker_heartbeat_at IS NULL
                    OR worker_heartbeat_at < ?
                  )""",
                (token, now, run_id, cutoff),
            )
        return cursor.rowcount == 1

    def heartbeat_run(self, run_id: str, token: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE strategy_runs SET worker_heartbeat_at=?
                WHERE run_id=? AND worker_token=? AND status='running'""",
                (utc_now(), run_id, token),
            )
        return cursor.rowcount == 1

    def release_run_worker(self, run_id: str, token: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE strategy_runs
                SET worker_token=NULL, worker_pid=NULL, worker_heartbeat_at=NULL
                WHERE run_id=? AND worker_token=?""",
                (run_id, token),
            )

    def update_task(self, task_id: str, **fields: Any) -> None:
        allowed = {
            "status", "pause_requested", "worker_token", "worker_pid",
            "worker_heartbeat_at", "current_job_id", "discovered_count",
            "deduped_count", "list_next_page", "output_path", "error_message",
            "last_run_id", "city_order",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        if "status" in updates and updates["status"] not in TASK_STATUSES:
            raise ValueError(f"未知任务状态: {updates['status']}")
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE tasks SET {assignments} WHERE task_id = ?",
                (*updates.values(), task_id),
            )

    def _merge_catalog_rows(
        self,
        connection: sqlite3.Connection,
        winner_id: str,
        loser_id: str,
    ) -> str:
        if winner_id == loser_id:
            return winner_id
        winner = dict(connection.execute(
            "SELECT * FROM job_catalog WHERE catalog_job_id=?", (winner_id,),
        ).fetchone())
        loser = dict(connection.execute(
            "SELECT * FROM job_catalog WHERE catalog_job_id=?", (loser_id,),
        ).fetchone())
        detail_source = (
            loser
            if len(str(loser["full_jd"] or "")) > len(str(winner["full_jd"] or ""))
            else winner
        )
        merged = {
            "source_job_id": winner["source_job_id"] or loser["source_job_id"],
            "job_name": winner["job_name"] or loser["job_name"],
            "city": winner["city"] or loser["city"],
            "salary_raw": winner["salary_raw"] or loser["salary_raw"],
            "salary_range": winner["salary_range"] or loser["salary_range"],
            "salary_months": winner["salary_months"] or loser["salary_months"],
            "job_type": winner["job_type"] or loser["job_type"],
            "experience": winner["experience"] or loser["experience"],
            "education": winner["education"] or loser["education"],
            "full_jd": detail_source["full_jd"],
            "job_url": winner["job_url"] or loser["job_url"],
            "normalized_job_url": (
                winner["normalized_job_url"] or loser["normalized_job_url"]
            ),
            "detail_url": detail_source["detail_url"],
            "labels": winner["labels"] or loser["labels"],
            "raw_json": winner["raw_json"] or loser["raw_json"],
            "crawl_status": detail_source["crawl_status"],
            "crawl_attempts": max(
                int(winner["crawl_attempts"]), int(loser["crawl_attempts"])
            ),
            "crawl_error": detail_source["crawl_error"],
            "error_message": detail_source["error_message"],
            "availability_status": (
                "confirmed_unavailable"
                if "confirmed_unavailable" in {
                    winner["availability_status"], loser["availability_status"],
                }
                else "available"
            ),
            "confirmed_unavailable_at": (
                winner["confirmed_unavailable_at"]
                or loser["confirmed_unavailable_at"]
            ),
            "first_captured_at": min(
                winner["first_captured_at"], loser["first_captured_at"]
            ),
        }
        connection.execute(
            """DELETE FROM jobs
            WHERE catalog_job_id=?
              AND EXISTS (
                  SELECT 1 FROM jobs AS winner_link
                  WHERE winner_link.task_id=jobs.task_id
                    AND winner_link.catalog_job_id=?
              )""",
            (loser_id, winner_id),
        )
        connection.execute(
            "UPDATE jobs SET catalog_job_id=? WHERE catalog_job_id=?",
            (winner_id, loser_id),
        )
        for loser_link in connection.execute(
            "SELECT * FROM strategy_jobs WHERE catalog_job_id=?",
            (loser_id,),
        ).fetchall():
            existing = connection.execute(
                """SELECT * FROM strategy_jobs
                WHERE strategy_id=? AND catalog_job_id=?""",
                (loser_link["strategy_id"], winner_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """UPDATE strategy_jobs SET catalog_job_id=?
                    WHERE strategy_id=? AND catalog_job_id=?""",
                    (winner_id, loser_link["strategy_id"], loser_id),
                )
                continue
            preferred = (
                loser_link
                if AI_STATUS_RANK.get(loser_link["ai_status"], 0)
                > AI_STATUS_RANK.get(existing["ai_status"], 0)
                else existing
            )
            first_seen = (
                loser_link
                if loser_link["first_seen_at"] < existing["first_seen_at"]
                else existing
            )
            last_seen = (
                loser_link
                if loser_link["last_seen_at"] > existing["last_seen_at"]
                else existing
            )
            connection.execute(
                """UPDATE strategy_jobs SET
                    first_seen_run_id=?, first_seen_task_id=?, first_seen_at=?,
                    last_seen_run_id=?, last_seen_task_id=?, last_seen_at=?,
                    ai_status=?, ai_attempts=?, ai_error=?, error_message=?,
                    job_responsibilities=?, job_requirements=?, bonus_points=?,
                    role_category=?, relevance_reason=?, relevance_confidence=?
                WHERE strategy_id=? AND catalog_job_id=?""",
                (
                    first_seen["first_seen_run_id"],
                    first_seen["first_seen_task_id"],
                    first_seen["first_seen_at"],
                    last_seen["last_seen_run_id"],
                    last_seen["last_seen_task_id"],
                    last_seen["last_seen_at"],
                    preferred["ai_status"],
                    max(int(existing["ai_attempts"]), int(loser_link["ai_attempts"])),
                    preferred["ai_error"], preferred["error_message"],
                    preferred["job_responsibilities"],
                    preferred["job_requirements"], preferred["bonus_points"],
                    preferred["role_category"], preferred["relevance_reason"],
                    preferred["relevance_confidence"],
                    existing["strategy_id"], winner_id,
                ),
            )
            connection.execute(
                """DELETE FROM strategy_jobs
                WHERE strategy_id=? AND catalog_job_id=?""",
                (loser_link["strategy_id"], loser_id),
            )
        connection.execute(
            "DELETE FROM job_catalog WHERE catalog_job_id=?", (loser_id,),
        )
        assignments = ", ".join(f"{field}=?" for field in merged)
        connection.execute(
            f"""UPDATE job_catalog SET {assignments}, last_updated_at=?
            WHERE catalog_job_id=?""",
            (*merged.values(), utc_now(), winner_id),
        )
        return winner_id

    def _upsert_catalog_job(
        self, connection: sqlite3.Connection, job: dict[str, Any],
    ) -> tuple[str, bool]:
        source_id = str(
            job.get("encrypt_job_id") or job.get("source_job_id") or ""
        ).strip()
        job_url = str(job.get("job_link") or job.get("job_url") or "").strip()
        normalized_url = normalize_job_url(job_url)
        if not source_id and not normalized_url:
            raise ValueError("策略岗位缺少稳定岗位 ID 和规范化链接")
        by_source = (
            connection.execute(
                "SELECT catalog_job_id FROM job_catalog WHERE source_job_id=?",
                (source_id,),
            ).fetchone()
            if source_id else None
        )
        by_url = (
            connection.execute(
                "SELECT catalog_job_id FROM job_catalog WHERE normalized_job_url=?",
                (normalized_url,),
            ).fetchone()
            if normalized_url else None
        )
        if by_source is None and by_url is None:
            catalog_id = uuid.uuid4().hex
            now = utc_now()
            connection.execute(
                """INSERT INTO job_catalog (
                    catalog_job_id, source_job_id, job_name, city, salary_raw,
                    salary_range, salary_months, job_type, experience, education,
                    full_jd, job_url, normalized_job_url, detail_url, labels,
                    raw_json, crawl_status, crawl_attempts, crawl_error,
                    error_message, first_captured_at, last_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    catalog_id, source_id,
                    str(job.get("title") or job.get("job_name") or ""),
                    normalize_city_name(
                        job.get("city_name") or job.get("location") or job.get("city")
                    ),
                    str(job.get("salary") or job.get("salary_raw") or ""),
                    str(job.get("salary_range") or "未注明"),
                    str(job.get("salary_months") or "未注明"),
                    str(job.get("job_type") or "未注明"),
                    str(job.get("experience") or ""),
                    str(job.get("education") or ""),
                    str(job.get("full_jd") or ""),
                    job_url, normalized_url,
                    str(job.get("detail_url") or ""),
                    str(job.get("job_labels") or job.get("labels") or ""),
                    _json_text(job, "{}"),
                    str(job.get("crawl_status") or "pending"),
                    int(job.get("crawl_attempts") or 0),
                    str(job.get("crawl_error") or ""),
                    str(job.get("error_message") or ""),
                    now, now,
                ),
            )
            return catalog_id, True
        catalog_id = (
            by_source["catalog_job_id"] if by_source is not None
            else by_url["catalog_job_id"]
        )
        if (
            by_source is not None
            and by_url is not None
            and by_source["catalog_job_id"] != by_url["catalog_job_id"]
        ):
            catalog_id = self._merge_catalog_rows(
                connection,
                by_source["catalog_job_id"],
                by_url["catalog_job_id"],
            )
        title = str(job.get("title") or job.get("job_name") or "")
        city = normalize_city_name(
            job.get("city_name") or job.get("location") or job.get("city")
        )
        salary = str(job.get("salary") or job.get("salary_raw") or "")
        labels = str(job.get("job_labels") or job.get("labels") or "")
        connection.execute(
            """UPDATE job_catalog SET
                source_job_id=CASE WHEN ?<>'' THEN ? ELSE source_job_id END,
                job_name=CASE WHEN ?<>'' THEN ? ELSE job_name END,
                city=CASE WHEN ?<>'' THEN ? ELSE city END,
                salary_raw=CASE WHEN ?<>'' THEN ? ELSE salary_raw END,
                job_url=CASE WHEN ?<>'' THEN ? ELSE job_url END,
                normalized_job_url=CASE WHEN ?<>'' THEN ? ELSE normalized_job_url END,
                labels=CASE WHEN ?<>'' THEN ? ELSE labels END,
                raw_json=?, last_updated_at=?
            WHERE catalog_job_id=?""",
            (
                source_id, source_id, title, title, city, city, salary, salary,
                job_url, job_url, normalized_url, normalized_url,
                labels, labels, _json_text(job, "{}"), utc_now(), catalog_id,
            ),
        )
        return catalog_id, False

    def _upsert_strategy_task_job(
        self, task: dict[str, Any], job: dict[str, Any],
    ) -> bool:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            catalog_id, _ = self._upsert_catalog_job(connection, job)
            existing_link = connection.execute(
                """SELECT job_id FROM jobs
                WHERE task_id=? AND catalog_job_id=?""",
                (task["task_id"], catalog_id),
            ).fetchone()
            inserted_link = existing_link is None
            if inserted_link:
                local_job_id = str(job.get("job_id") or catalog_id)
                now = utc_now()
                try:
                    connection.execute(
                        """INSERT INTO jobs (
                            task_id, job_id, catalog_job_id, captured_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?)""",
                        (task["task_id"], local_job_id, catalog_id, now, now),
                    )
                except sqlite3.IntegrityError:
                    connection.execute(
                        """INSERT INTO jobs (
                            task_id, job_id, catalog_job_id, captured_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?)""",
                        (task["task_id"], catalog_id, catalog_id, now, now),
                    )
            now = utc_now()
            run_id = task["last_run_id"] or task["first_run_id"]
            connection.execute(
                """INSERT INTO strategy_jobs (
                    strategy_id, catalog_job_id,
                    first_seen_run_id, last_seen_run_id,
                    first_seen_task_id, last_seen_task_id,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id, catalog_job_id) DO UPDATE SET
                    last_seen_run_id=excluded.last_seen_run_id,
                    last_seen_task_id=excluded.last_seen_task_id,
                    last_seen_at=excluded.last_seen_at""",
                (
                    task["strategy_id"], catalog_id, run_id, run_id,
                    task["task_id"], task["task_id"], now, now,
                ),
            )
            connection.commit()
            return inserted_link
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def upsert_job(self, task_id: str, job: dict[str, Any]) -> bool:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if task["strategy_id"]:
            return self._upsert_strategy_task_job(task, job)
        job_id = str(job.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("岗位缺少 job_id")
        now = utc_now()
        raw = _json_text(job, "{}")
        job_url = str(job.get("job_link") or job.get("job_url") or "")
        normalized_url = normalize_job_url(job_url)
        values = (
            task_id, job_id, str(job.get("encrypt_job_id") or job.get("source_job_id") or ""),
            str(job.get("title") or job.get("job_name") or ""),
            normalize_city_name(
                job.get("city_name") or job.get("location") or job.get("city")
            ),
            str(job.get("salary") or job.get("salary_raw") or ""),
            str(job.get("salary_range") or "未注明"), str(job.get("salary_months") or "未注明"),
            str(job.get("job_type") or "未注明"), str(job.get("experience") or ""),
            str(job.get("education") or ""), job_url, normalized_url,
            str(job.get("job_labels") or job.get("labels") or ""), raw, now, now,
        )
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """SELECT job_id FROM jobs WHERE task_id=?
                AND (job_id=? OR (? <> '' AND normalized_job_url=?))
                ORDER BY CASE WHEN job_id=? THEN 0 ELSE 1 END LIMIT 1""",
                (task_id, job_id, normalized_url, normalized_url, job_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO jobs (
                    task_id, job_id, source_job_id, job_name, city, salary_raw,
                    salary_range, salary_months, job_type, experience, education,
                    job_url, normalized_job_url, labels, raw_json, captured_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
                connection.commit()
                return True
            existing_job_id = existing["job_id"]
            connection.execute(
                """UPDATE jobs SET source_job_id=?, job_name=?, city=?, salary_raw=?,
                experience=?, education=?, job_url=?, normalized_job_url=?, labels=?,
                raw_json=?, updated_at=? WHERE task_id=? AND job_id=?""",
                (
                    values[2], values[3], values[4], values[5], values[9], values[10],
                    values[11], values[12], values[13], values[14], now, task_id,
                    existing_job_id,
                ),
            )
            connection.commit()
            return False
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_job(self, task_id: str, job_id: str, **fields: Any) -> None:
        task = self.get_task(task_id)
        if task is not None and task["strategy_id"]:
            self._update_strategy_job(task, job_id, fields)
            return
        allowed = {
            "job_name", "city", "salary_raw", "salary_range", "salary_months",
            "job_type", "experience", "education", "full_jd", "job_responsibilities",
            "job_requirements", "bonus_points", "job_url", "normalized_job_url",
            "detail_url", "labels",
            "raw_json", "crawl_status", "ai_status", "crawl_attempts", "ai_attempts",
            "error_message", "crawl_error", "ai_error", "role_category",
            "relevance_reason", "relevance_confidence",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        if "job_url" in updates and "normalized_job_url" not in updates:
            updates["normalized_job_url"] = normalize_job_url(updates["job_url"])
        if "crawl_status" in updates and updates["crawl_status"] not in CRAWL_STATUSES:
            raise ValueError(f"未知采集状态: {updates['crawl_status']}")
        if "ai_status" in updates and updates["ai_status"] not in AI_STATUSES:
            raise ValueError(f"未知 AI 状态: {updates['ai_status']}")
        for key in ("job_responsibilities", "job_requirements", "bonus_points", "raw_json"):
            if key in updates:
                updates[key] = _json_text(updates[key], "")
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {assignments} WHERE task_id = ? AND job_id = ?",
                (*updates.values(), task_id, job_id),
            )

    def _strategy_job_rows(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT
                    links.task_id, links.job_id, catalog.catalog_job_id,
                    catalog.source_job_id, catalog.job_name, catalog.city,
                    catalog.salary_raw, catalog.salary_range, catalog.salary_months,
                    catalog.job_type, catalog.experience, catalog.education,
                    catalog.full_jd, strategy_jobs.job_responsibilities,
                    strategy_jobs.job_requirements, strategy_jobs.bonus_points,
                    catalog.job_url, catalog.normalized_job_url, catalog.detail_url,
                    catalog.labels, catalog.raw_json, catalog.crawl_status,
                    strategy_jobs.ai_status, catalog.crawl_attempts,
                    strategy_jobs.ai_attempts, links.captured_at,
                    catalog.last_updated_at AS updated_at,
                    CASE
                        WHEN strategy_jobs.error_message<>'' THEN strategy_jobs.error_message
                        ELSE catalog.error_message
                    END AS error_message,
                    catalog.crawl_error, strategy_jobs.ai_error,
                    strategy_jobs.role_category, strategy_jobs.relevance_reason,
                    strategy_jobs.relevance_confidence,
                    catalog.availability_status, catalog.confirmed_unavailable_at
                FROM jobs AS links
                JOIN job_catalog AS catalog
                  ON catalog.catalog_job_id=links.catalog_job_id
                JOIN strategy_jobs
                  ON strategy_jobs.strategy_id=?
                 AND strategy_jobs.catalog_job_id=catalog.catalog_job_id
                WHERE links.task_id=?
                ORDER BY links.captured_at, links.job_id""",
                (task["strategy_id"], task["task_id"]),
            ).fetchall()
        return [dict(row) for row in rows]

    def _update_strategy_job(
        self, task: dict[str, Any], job_id: str, fields: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            link = connection.execute(
                """SELECT catalog_job_id FROM jobs
                WHERE task_id=? AND job_id=?""",
                (task["task_id"], job_id),
            ).fetchone()
            if link is None:
                raise KeyError((task["task_id"], job_id))
            catalog_updates = {
                key: value for key, value in fields.items()
                if key in CATALOG_UPDATE_FIELDS
            }
            strategy_updates = {
                key: value for key, value in fields.items()
                if key in STRATEGY_AI_UPDATE_FIELDS
            }
            if "error_message" in fields:
                if "ai_status" in fields or "ai_error" in fields:
                    catalog_updates.pop("error_message", None)
                else:
                    strategy_updates.pop("error_message", None)
            if (
                "job_url" in catalog_updates
                and "normalized_job_url" not in catalog_updates
            ):
                catalog_updates["normalized_job_url"] = normalize_job_url(
                    catalog_updates["job_url"]
                )
            if (
                "crawl_status" in catalog_updates
                and catalog_updates["crawl_status"] not in CRAWL_STATUSES
            ):
                raise ValueError(
                    f"未知采集状态: {catalog_updates['crawl_status']}"
                )
            if (
                "ai_status" in strategy_updates
                and strategy_updates["ai_status"] not in AI_STATUSES
            ):
                raise ValueError(f"未知 AI 状态: {strategy_updates['ai_status']}")
            if "raw_json" in catalog_updates:
                catalog_updates["raw_json"] = _json_text(
                    catalog_updates["raw_json"], "{}"
                )
            for key in ("job_responsibilities", "job_requirements", "bonus_points"):
                if key in strategy_updates:
                    strategy_updates[key] = _json_text(strategy_updates[key], "")
            if catalog_updates:
                catalog_updates["last_updated_at"] = utc_now()
                assignments = ", ".join(f"{key}=?" for key in catalog_updates)
                connection.execute(
                    f"""UPDATE job_catalog SET {assignments}
                    WHERE catalog_job_id=?""",
                    (*catalog_updates.values(), link["catalog_job_id"]),
                )
            if strategy_updates:
                assignments = ", ".join(f"{key}=?" for key in strategy_updates)
                connection.execute(
                    f"""UPDATE strategy_jobs SET {assignments}
                    WHERE strategy_id=? AND catalog_job_id=?""",
                    (
                        *strategy_updates.values(),
                        task["strategy_id"], link["catalog_job_id"],
                    ),
                )

    def list_jobs(self, task_id: str) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        if task is not None and task["strategy_id"]:
            return self._strategy_job_rows(task)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE task_id = ? ORDER BY captured_at, job_id", (task_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def next_jobs(self, task_id: str, phase: str, limit: int | None = None) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        if task is not None and task["strategy_id"]:
            rows = self._strategy_job_rows(task)
            if phase == "crawl":
                rows = [
                    row for row in rows
                    if row["crawl_status"] in {
                        "pending", "failed", "waiting_for_login",
                    }
                ]
            elif phase == "ai":
                rows = [
                    row for row in rows
                    if row["crawl_status"] == "completed"
                    and row["ai_status"] in {
                        "pending", "failed", "waiting_for_ai",
                    }
                ]
            else:
                raise ValueError(f"未知处理阶段: {phase}")
            return rows if limit is None else rows[:max(1, int(limit))]
        if phase == "crawl":
            predicate = "crawl_status IN ('pending', 'failed', 'waiting_for_login')"
        elif phase == "ai":
            predicate = "crawl_status = 'completed' AND ai_status IN ('pending', 'failed', 'waiting_for_ai')"
        else:
            raise ValueError(f"未知处理阶段: {phase}")
        sql = f"SELECT * FROM jobs WHERE task_id = ? AND {predicate} ORDER BY captured_at, job_id"
        params: list[Any] = [task_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_strategy_jobs(self, strategy_id: str) -> list[dict[str, Any]]:
        if self.get_strategy(strategy_id) is None:
            raise KeyError(strategy_id)
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT
                    catalog.*, strategy_jobs.ai_status,
                    strategy_jobs.ai_attempts, strategy_jobs.ai_error,
                    strategy_jobs.error_message AS strategy_error_message,
                    strategy_jobs.job_responsibilities,
                    strategy_jobs.job_requirements, strategy_jobs.bonus_points,
                    strategy_jobs.role_category, strategy_jobs.relevance_reason,
                    strategy_jobs.relevance_confidence,
                    strategy_jobs.first_seen_at, strategy_jobs.last_seen_at
                FROM strategy_jobs
                JOIN job_catalog AS catalog
                  ON catalog.catalog_job_id=strategy_jobs.catalog_job_id
                WHERE strategy_jobs.strategy_id=?
                ORDER BY strategy_jobs.first_seen_at, catalog.catalog_job_id""",
                (strategy_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_strategy_jobs_as_of_run(
        self, strategy_id: str, run_id: str,
    ) -> list[dict[str, Any]]:
        run = self.get_run(run_id)
        if run is None or run["strategy_id"] != strategy_id:
            raise KeyError(run_id)
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT
                    catalog.*, strategy_jobs.ai_status,
                    strategy_jobs.ai_attempts, strategy_jobs.ai_error,
                    strategy_jobs.error_message AS strategy_error_message,
                    strategy_jobs.job_responsibilities,
                    strategy_jobs.job_requirements, strategy_jobs.bonus_points,
                    strategy_jobs.role_category, strategy_jobs.relevance_reason,
                    strategy_jobs.relevance_confidence,
                    strategy_jobs.first_seen_at, strategy_jobs.last_seen_at
                FROM strategy_jobs
                JOIN job_catalog AS catalog
                  ON catalog.catalog_job_id=strategy_jobs.catalog_job_id
                JOIN strategy_runs AS first_run
                  ON first_run.run_id=strategy_jobs.first_seen_run_id
                WHERE strategy_jobs.strategy_id=?
                  AND first_run.run_number <= ?
                ORDER BY strategy_jobs.first_seen_at, catalog.catalog_job_id""",
                (strategy_id, int(run["run_number"])),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_catalog_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_catalog "
                "ORDER BY first_captured_at, catalog_job_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def count_catalog_jobs(self) -> int:
        with self.connect() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM job_catalog"
            ).fetchone()[0])

    def reserve_worker(self, task_id: str, token: str, stale_seconds: int = 60) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)).isoformat()
        now = utc_now()
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                """SELECT task_id FROM tasks WHERE worker_token IS NOT NULL
                AND worker_heartbeat_at >= ? AND task_id <> ? LIMIT 1""",
                (cutoff, task_id),
            ).fetchone()
            own = connection.execute(
                "SELECT worker_token, worker_heartbeat_at FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if active or own is None:
                connection.rollback()
                return False
            if own["worker_token"] and (own["worker_heartbeat_at"] or "") >= cutoff:
                connection.rollback()
                return False
            connection.execute(
                """UPDATE tasks SET worker_token=?, worker_heartbeat_at=?, status='processing',
                pause_requested=0, error_message='', updated_at=? WHERE task_id=?""",
                (token, now, now, task_id),
            )
            connection.commit()
            return True
        finally:
            connection.close()

    def attach_worker_pid(self, task_id: str, token: str, pid: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE tasks SET worker_pid=?, updated_at=? WHERE task_id=? AND worker_token=?",
                (int(pid), utc_now(), task_id, token),
            )

    def heartbeat(self, task_id: str, token: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET worker_heartbeat_at=?, updated_at=? WHERE task_id=? AND worker_token=?",
                (now, now, task_id, token),
            )
        return cursor.rowcount == 1

    def release_worker(self, task_id: str, token: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE tasks SET worker_token=NULL, worker_pid=NULL,
                worker_heartbeat_at=NULL, current_job_id=NULL, updated_at=?
                WHERE task_id=? AND worker_token=?""",
                (utc_now(), task_id, token),
            )

    def recover_interrupted(self, stale_seconds: int = 60) -> list[str]:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)).isoformat()
        recovered: list[str] = []
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT task_id, pause_requested, strategy_id FROM tasks
                WHERE (worker_token IS NOT NULL
                    AND (worker_heartbeat_at IS NULL OR worker_heartbeat_at < ?))
                OR (status='processing' AND worker_token IS NULL)""",
                (cutoff,),
            ).fetchall()
            for row in rows:
                task_id = row["task_id"]
                recovered.append(task_id)
                task_status = "paused" if row["pause_requested"] else "pending"
                connection.execute(
                    """UPDATE tasks SET status=?, worker_token=NULL, worker_pid=NULL,
                    worker_heartbeat_at=NULL, current_job_id=NULL, updated_at=? WHERE task_id=?""",
                    (task_status, utc_now(), task_id),
                )
                if row["strategy_id"]:
                    connection.execute(
                        """UPDATE job_catalog
                        SET crawl_status='pending', last_updated_at=?
                        WHERE crawl_status='processing'
                          AND catalog_job_id IN (
                              SELECT catalog_job_id FROM jobs WHERE task_id=?
                          )""",
                        (utc_now(), task_id),
                    )
                    connection.execute(
                        """UPDATE strategy_jobs SET ai_status='pending'
                        WHERE strategy_id=? AND ai_status='processing'
                          AND catalog_job_id IN (
                              SELECT catalog_job_id FROM jobs WHERE task_id=?
                          )""",
                        (row["strategy_id"], task_id),
                    )
                else:
                    connection.execute(
                        "UPDATE jobs SET crawl_status='pending', updated_at=? "
                        "WHERE task_id=? AND crawl_status='processing'",
                        (utc_now(), task_id),
                    )
                    connection.execute(
                        "UPDATE jobs SET ai_status='pending', updated_at=? "
                        "WHERE task_id=? AND ai_status='processing'",
                        (utc_now(), task_id),
                    )
        return recovered

    def set_state(self, key: str, value: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO app_state(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, value, now),
            )

    def get_state(self, key: str, default: str = "") -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def snapshot(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if task["strategy_id"]:
            rows = self._strategy_job_rows(task)
            task.update({
                "deduped": len(rows),
                "details_done": sum(
                    row["crawl_status"] == "completed" for row in rows
                ),
                "ai_done": sum(row["ai_status"] == "completed" for row in rows),
                "qualified": sum(
                    row["crawl_status"] == "completed"
                    and row["ai_status"] == "completed"
                    for row in rows
                ),
                "irrelevant": sum(
                    row["ai_status"] == "irrelevant" for row in rows
                ),
                "manual_review": sum(
                    row["ai_status"] == "manual_review" for row in rows
                ),
                "failed": sum(
                    row["crawl_status"] in {"failed", "invalid"}
                    or row["ai_status"] in {"failed", "invalid"}
                    for row in rows
                ),
            })
            return task
        with self.connect() as connection:
            counts = connection.execute(
                """SELECT
                COUNT(*) AS deduped,
                SUM(CASE WHEN crawl_status='completed' THEN 1 ELSE 0 END) AS details_done,
                SUM(CASE WHEN ai_status='completed' THEN 1 ELSE 0 END) AS ai_done,
                SUM(CASE WHEN crawl_status='completed' AND ai_status='completed' THEN 1 ELSE 0 END) AS qualified,
                SUM(CASE WHEN ai_status='irrelevant' THEN 1 ELSE 0 END) AS irrelevant,
                SUM(CASE WHEN ai_status='manual_review' THEN 1 ELSE 0 END) AS manual_review,
                SUM(CASE WHEN crawl_status IN ('failed','invalid') OR ai_status IN ('failed','invalid') THEN 1 ELSE 0 END) AS failed
                FROM jobs WHERE task_id=?""",
                (task_id,),
            ).fetchone()
        task.update({key: int(counts[key] or 0) for key in counts.keys()})
        return task
