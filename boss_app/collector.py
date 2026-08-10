"""Resumable orchestration around the existing CDP collection core."""

from __future__ import annotations

import json
import os
import queue
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from scripts import boss_cdp_raw as core

from .ai_parser import AIConfig, AIParseError, JDParser
from .db import (
    Database, normalize_city_name, uses_ai_relevance_filter,
    uses_qualified_target, utc_now,
)
from .job_type_parser import normalize_job_type
from .login_manager import LoginManager, LoginStatus
from .request_budget import RequestBudgetExhausted
from .salary_parser import parse_salary


class Collector:
    def __init__(
        self,
        database: Database,
        cdp_port: int = core.DEFAULT_CDP_PORT,
        ai_parser: JDParser | None = None,
        core_module=core,
        sleep_fn=time.sleep,
        jitter_fn=random.uniform,
        request_budget=None,
    ):
        self.database = database
        self.cdp_port = cdp_port
        self.ai_parser = ai_parser or JDParser(AIConfig.from_env())
        self.core = core_module
        self.sleep_fn = sleep_fn
        self.jitter_fn = jitter_fn
        self.request_budget = request_budget
        self.detail_max_retries = max(1, int(os.environ.get("BOSS_DETAIL_MAX_RETRIES", "2")))
        self.network_interval_min = max(
            0.0, float(os.environ.get("BOSS_NETWORK_INTERVAL_MIN", "2.0")),
        )
        self.network_interval_max = max(
            self.network_interval_min,
            float(os.environ.get("BOSS_NETWORK_INTERVAL_MAX", "5.0")),
        )

    def _network_pause(self) -> None:
        seconds = self.jitter_fn(self.network_interval_min, self.network_interval_max)
        if seconds > 0:
            self.sleep_fn(seconds)

    def _is_access_error(self, error: BaseException) -> bool:
        checker = getattr(self.core, "is_access_restriction_error", None)
        return bool(checker and checker(error))

    def _wait_for_access(
        self, task_id: str, message: str, job_id: str | None = None,
        crawl_attempts: int | None = None,
    ) -> None:
        self.database.set_state("last_login_success_at", "")
        if job_id:
            job_fields: dict[str, Any] = {
                "crawl_status": "pending", "crawl_error": message,
                "error_message": message,
            }
            if crawl_attempts is not None:
                job_fields["crawl_attempts"] = crawl_attempts
            self.database.update_job(task_id, job_id, **job_fields)
        self.database.update_task(
            task_id, status="waiting_for_access", current_job_id=None,
            error_message=message,
        )

    def _paused(self, task_id: str) -> bool:
        task = self.database.get_task(task_id)
        return bool(task and task["pause_requested"])

    def _checkpoint(self, task_id: str, token: str) -> bool:
        self.database.heartbeat(task_id, token)
        if self._paused(task_id):
            self.database.update_task(task_id, status="paused", current_job_id=None)
            return True
        return False

    @staticmethod
    def _requires_ai_operations_gate(task: dict[str, Any]) -> bool:
        return uses_qualified_target(task.get("keyword"), task.get("city"))

    @staticmethod
    def _requires_ai_relevance(task: dict[str, Any]) -> bool:
        return (
            bool(str(task.get("target_role") or "").strip())
            or
            uses_qualified_target(task.get("keyword"), task.get("city"))
            or uses_ai_relevance_filter(task.get("keyword"), task.get("city"))
        )

    @staticmethod
    def _source_job(row: dict[str, Any]) -> dict[str, Any]:
        try:
            source = json.loads(row.get("raw_json") or "{}")
        except (json.JSONDecodeError, TypeError, ValueError):
            source = {}
        if not isinstance(source, dict):
            source = {}
        source.update({
            "job_id": row["job_id"],
            "job_link": row["job_url"],
            "title": row["job_name"],
            "location": row["city"],
            "salary": row["salary_raw"],
            "encrypt_job_id": row["source_job_id"],
            "job_labels": row["labels"],
        })
        return source

    def _collect_list(
        self,
        task: dict[str, Any],
        token: str,
        *,
        one_page: bool = False,
    ) -> bool:
        task_id = task["task_id"]
        latest_task = self.database.get_task(task_id) or task
        start_page = max(1, int(latest_task.get("list_next_page") or 1))
        existing_jobs = self.database.list_jobs(task_id)
        current_count = (
            self.database.snapshot(task_id)["qualified"]
            if self._requires_ai_operations_gate(task)
            else len(existing_jobs)
        )
        if current_count >= task["max_jobs"]:
            return True
        remaining = task["max_jobs"] - current_count
        discovered = max(int(task["discovered_count"] or 0), current_count)

        def on_job(job: dict[str, Any]) -> bool:
            nonlocal discovered
            discovered += 1
            salary = parse_salary(job.get("salary"))
            job["salary_range"] = salary.salary_range
            job["salary_months"] = salary.salary_months
            job["job_type"] = normalize_job_type(job.get("title", ""), job.get("job_labels", ""))
            inserted = self.database.upsert_job(task_id, job)
            self.database.update_task(
                task_id,
                discovered_count=discovered,
                deduped_count=len(self.database.list_jobs(task_id)),
            )
            self.database.set_state("last_login_success_at", utc_now())
            self.database.heartbeat(task_id, token)
            return inserted

        def on_page_complete(next_page: int) -> None:
            self.database.update_task(
                task_id, list_next_page=max(1, int(next_page)),
            )

        filters = {
            key: value for key, value in {
                "salary": task["salary_filter"],
                "experience": task["experience_filter"],
                "degree": task["degree_filter"],
            }.items() if value
        }
        output_dir = self.database.path.parent / "job-result" / task_id
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.core.scrape_list(
                task["keyword"], task["city"], task["max_pages"], filters,
                str(output_dir / "jobs.json"), cdp_port=self.cdp_port,
                max_jobs=remaining, on_job=on_job,
                should_stop=lambda: self._paused(task_id),
                raise_errors=True,
                existing_keys={row["job_url"] or row["job_name"] for row in existing_jobs},
                start_page=start_page,
                on_page_complete=on_page_complete,
                request_budget=self.request_budget,
                page_limit=1 if one_page else None,
            )
        except (KeyError, OSError, RuntimeError, TimeoutError) as exc:
            if self._is_access_error(exc):
                self._wait_for_access(task_id, str(exc))
                return False
            raise
        return not self._paused(task_id)

    def _collect_details(self, task_id: str, token: str) -> bool:
        rows = self.database.next_jobs(task_id, "crawl")
        task = self.database.get_task(task_id)
        requires_relevance = bool(task and self._requires_ai_relevance(task))
        ai_stop = threading.Event()
        first_ai_claimed = threading.Event()
        ai_errors: list[BaseException] = []
        access_failure: tuple[str, str, int] | None = None
        ai_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def consume_ai() -> None:
            while True:
                queued_row = ai_queue.get()
                try:
                    if queued_row is None:
                        return
                    if ai_stop.is_set():
                        continue
                    if not self._process_ai_row(
                        task_id, token, queued_row,
                        requires_relevance=requires_relevance,
                        started_event=first_ai_claimed,
                    ):
                        ai_stop.set()
                except BaseException as exc:
                    ai_errors.append(exc)
                    ai_stop.set()
                finally:
                    ai_queue.task_done()

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="boss-ai") as executor:
            executor.submit(consume_ai)
            try:
                for index, row in enumerate(rows):
                    if ai_stop.is_set() or row["crawl_attempts"] >= self.detail_max_retries:
                        if ai_stop.is_set():
                            break
                        continue
                    if self._checkpoint(task_id, token):
                        return False
                    attempts = row["crawl_attempts"] + 1
                    self.database.update_task(task_id, current_job_id=row["job_id"])
                    self.database.update_job(
                        task_id, row["job_id"], crawl_status="processing",
                        crawl_attempts=attempts, crawl_error="",
                    )
                    try:
                        detail = self.core.fetch_job_detail(
                            self._source_job(row), cdp_port=self.cdp_port,
                            request_budget=self.request_budget,
                        )
                        salary = parse_salary(detail.get("salary") or row["salary_raw"])
                        job_type = normalize_job_type(
                            detail.get("title") or row["job_name"], row["labels"],
                            detail.get("jd", ""),
                        )
                        self.database.update_job(
                            task_id, row["job_id"],
                            job_name=detail.get("title") or row["job_name"],
                            city=row["city"] or normalize_city_name(detail.get("location")),
                            salary_raw=salary.raw, salary_range=salary.salary_range,
                            salary_months=salary.salary_months, job_type=job_type,
                            full_jd=detail.get("jd", ""),
                            detail_url=detail.get("detail_url", ""),
                            crawl_status="completed", crawl_error="", error_message="",
                        )
                        self.database.set_state("last_login_success_at", utc_now())
                        if not ai_stop.is_set():
                            completed_row = next(
                                saved for saved in self.database.list_jobs(task_id)
                                if saved["job_id"] == row["job_id"]
                            )
                            wait_for_claim = not first_ai_claimed.is_set()
                            ai_queue.put(completed_row)
                            if wait_for_claim:
                                while not first_ai_claimed.wait(0.01) and not ai_stop.is_set():
                                    pass
                                ai_stop.wait(0.05)
                    except RequestBudgetExhausted:
                        self.database.update_job(
                            task_id,
                            row["job_id"],
                            crawl_status="pending",
                            crawl_attempts=row["crawl_attempts"],
                            crawl_error="",
                            error_message="",
                        )
                        self.database.update_task(task_id, current_job_id=None)
                        raise
                    except self.core.DetailLoginRequiredError as exc:
                        self.database.update_job(
                            task_id, row["job_id"], crawl_status="waiting_for_login",
                            crawl_error=str(exc), error_message=str(exc),
                        )
                        self.database.update_task(
                            task_id, status="waiting_for_login", error_message=str(exc),
                        )
                        return False
                    except self.core.DetailExtractionError as exc:
                        status = "invalid" if attempts >= self.detail_max_retries else "failed"
                        self.database.update_job(
                            task_id, row["job_id"], crawl_status=status,
                            crawl_error=str(exc), error_message=str(exc),
                        )
                    except (KeyError, OSError, RuntimeError, TimeoutError) as exc:
                        if self._is_access_error(exc):
                            access_failure = (str(exc), row["job_id"], row["crawl_attempts"])
                            break
                        self.database.update_job(
                            task_id, row["job_id"], crawl_status="failed",
                            crawl_error=str(exc), error_message=str(exc),
                        )
                    if self._checkpoint(task_id, token):
                        return False
                    if index < len(rows) - 1:
                        self._network_pause()
            finally:
                ai_queue.put(None)

        if access_failure:
            self._wait_for_access(task_id, *access_failure)
            return False
        if ai_errors:
            raise RuntimeError(f"AI worker failed: {ai_errors[0]}") from ai_errors[0]
        return not ai_stop.is_set()

    def _process_ai_row(
        self,
        task_id: str,
        token: str,
        row: dict[str, Any],
        *,
        requires_relevance: bool,
        started_event: threading.Event | None = None,
    ) -> bool:
        """Process one complete JD; return False when the task must stop."""
        if self._checkpoint(task_id, token):
            return False
        if not self.ai_parser.config.configured:
            self.database.update_job(
                task_id, row["job_id"], ai_status="waiting_for_ai",
                job_responsibilities="待处理", job_requirements="待处理",
                bonus_points="待处理", ai_error="AI 配置不完整",
            )
            self.database.update_task(task_id, status="waiting_for_ai", error_message="AI 配置不完整")
            return False
        attempts = row["ai_attempts"] + 1
        if not str(row["full_jd"] or "").strip():
            self.database.update_job(
                task_id, row["job_id"], ai_status="invalid", ai_attempts=attempts,
                job_responsibilities="待处理", job_requirements="待处理",
                bonus_points="待处理", ai_error="完整 JD 为空",
            )
            return not self._checkpoint(task_id, token)
        self.database.update_job(
            task_id, row["job_id"], ai_status="processing", ai_attempts=attempts,
        )
        if started_event is not None:
            started_event.set()
        try:
            task = self.database.get_task(task_id) or {}
            context = {"job_name": row["job_name"], "labels": row["labels"]}
            target_role = str(task.get("target_role") or "").strip()
            if target_role:
                parsed = self.ai_parser.parse_target(
                    row["full_jd"], target_role=target_role,
                    target_type=str(task.get("target_type") or ""), context=context,
                )
                ai_status = {
                    "matched": "completed",
                    "manual_review": "manual_review",
                    "irrelevant": "irrelevant",
                }[parsed.match_status]
                relevance_fields = {
                    "role_category": parsed.role_category,
                    "relevance_reason": parsed.relevance_reason,
                    "relevance_confidence": parsed.relevance_confidence,
                }
            else:
                parsed = self.ai_parser.parse(row["full_jd"], context)
                ai_status = (
                    "completed" if parsed.is_ai_operations or not requires_relevance
                    else "irrelevant"
                )
                relevance_fields = {}
            self.database.update_job(
                task_id, row["job_id"],
                ai_status=ai_status,
                ai_error="",
                job_type=parsed.job_type,
                job_responsibilities=parsed.job_responsibilities,
                job_requirements=parsed.job_requirements,
                bonus_points=parsed.bonus_points,
                **relevance_fields,
            )
        except AIParseError as exc:
            self.database.update_job(
                task_id, row["job_id"], ai_status="waiting_for_ai",
                job_responsibilities="待处理", job_requirements="待处理",
                bonus_points="待处理", ai_error=str(exc), error_message=str(exc),
            )
            self.database.update_task(
                task_id, status="waiting_for_ai", error_message=str(exc),
            )
            return False
        return not self._checkpoint(task_id, token)

    def _process_ai(self, task_id: str, token: str) -> bool:
        task = self.database.get_task(task_id)
        requires_relevance = bool(task and self._requires_ai_relevance(task))
        for row in self.database.next_jobs(task_id, "ai"):
            if not self._process_ai_row(
                task_id, token, row, requires_relevance=requires_relevance,
            ):
                return False
        return True

    def drain_ai(self, task_id: str, token: str) -> bool:
        """Process only saved complete JDs and leave city completion to the Runner."""
        return self._process_ai(task_id, token)

    def _run_strategy_batches(self, task_id: str, token: str) -> bool:
        """Drain one saved page before asking BOSS for the next list page."""
        while True:
            task = self.database.get_task(task_id)
            if task is None:
                raise KeyError(task_id)
            requires_gate = self._requires_ai_operations_gate(task)

            if not self._collect_details(task_id, token):
                return False
            if not self._process_ai(task_id, token):
                return False
            if self._paused(task_id):
                self.database.update_task(
                    task_id, status="paused", current_job_id=None,
                )
                return False

            task = self.database.get_task(task_id)
            if task is None:
                raise KeyError(task_id)
            jobs = self.database.list_jobs(task_id)
            if any(row["ai_status"] == "waiting_for_ai" for row in jobs):
                self.database.update_task(
                    task_id, status="waiting_for_ai", current_job_id=None,
                )
                return False

            snapshot = self.database.snapshot(task_id)
            current_count = snapshot["qualified"] if requires_gate else len(jobs)
            pages_exhausted = (
                int(task["list_next_page"]) > int(task["max_pages"])
            )
            if current_count >= int(task["max_jobs"]) or pages_exhausted:
                return True

            retryable_details = any(
                row["crawl_attempts"] < self.detail_max_retries
                for row in self.database.next_jobs(task_id, "crawl")
            )
            if retryable_details:
                self._network_pause()
                continue

            if not self._collect_list(task, token, one_page=True):
                current = self.database.get_task(task_id)
                if (
                    current
                    and current["status"] != "waiting_for_access"
                    and self._paused(task_id)
                ):
                    self.database.update_task(
                        task_id, status="paused", current_job_id=None,
                    )
                return False
            self._network_pause()

    def run_existing(self, task_id: str, token: str) -> None:
        """Process candidates already saved for a task without listing again."""
        self.run(task_id, token, existing_only=True)

    def run(
        self,
        task_id: str,
        token: str,
        ai_only: bool = False,
        existing_only: bool = False,
    ) -> None:
        task = self.database.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        self.database.update_task(task_id, status="processing", error_message="")
        requires_gate = self._requires_ai_operations_gate(task)
        if not self._process_ai(task_id, token):
            return
        if not ai_only:
            login = LoginManager(
                self.database,
                self.cdp_port,
                request_budget=self.request_budget,
            ).status(
                probe=True, allow_recent=True,
            )
            if login.status is LoginStatus.RESTRICTED:
                self._wait_for_access(task_id, login.message or login.status.value)
                return
            if login.status is not LoginStatus.LOGGED_IN:
                self.database.update_task(
                    task_id, status="waiting_for_login", error_message=login.message or login.status.value,
                )
                return
        if existing_only and not ai_only:
            if not self._collect_details(task_id, token):
                return
        elif task["strategy_id"] and not ai_only:
            if not self._run_strategy_batches(task_id, token):
                return
        elif requires_gate and not ai_only:
            while True:
                before = self.database.snapshot(task_id)
                if before["qualified"] >= task["max_jobs"]:
                    self.database.update_task(
                        task_id, status="completed", current_job_id=None,
                    )
                    return
                if not self._collect_details(task_id, token):
                    return
                if not self._process_ai(task_id, token):
                    return
                if self._paused(task_id):
                    self.database.update_task(
                        task_id, status="paused", current_job_id=None,
                    )
                    return
                jobs = self.database.list_jobs(task_id)
                if any(job["ai_status"] == "waiting_for_ai" for job in jobs):
                    self.database.update_task(
                        task_id, status="waiting_for_ai", current_job_id=None,
                    )
                    return
                processed = self.database.snapshot(task_id)
                if processed["qualified"] >= task["max_jobs"]:
                    self.database.update_task(
                        task_id, status="completed", current_job_id=None,
                    )
                    return
                retryable_details = any(
                    row["crawl_attempts"] < self.detail_max_retries
                    for row in self.database.next_jobs(task_id, "crawl")
                )
                if retryable_details:
                    self._network_pause()
                    continue
                if not self._collect_list(task, token):
                    current = self.database.get_task(task_id)
                    if current and current["status"] != "waiting_for_access":
                        self.database.update_task(task_id, status="paused")
                    return
                after_list = self.database.snapshot(task_id)
                if after_list["deduped"] == processed["deduped"]:
                    self.database.update_task(
                        task_id, status="incomplete", current_job_id=None,
                    )
                    return
        elif not ai_only:
            if not self._collect_list(task, token):
                current = self.database.get_task(task_id)
                if current and current["status"] != "waiting_for_access":
                    self.database.update_task(task_id, status="paused")
                return
            if not self._collect_details(task_id, token):
                return
        if not self._process_ai(task_id, token):
            return
        if self._paused(task_id):
            self.database.update_task(task_id, status="paused", current_job_id=None)
            return
        snapshot = self.database.snapshot(task_id)
        if any(job["ai_status"] == "waiting_for_ai" for job in self.database.list_jobs(task_id)):
            self.database.update_task(task_id, status="waiting_for_ai", current_job_id=None)
        elif requires_gate and not existing_only and snapshot["qualified"] < task["max_jobs"]:
            self.database.update_task(task_id, status="incomplete", current_job_id=None)
        elif snapshot["failed"]:
            self.database.update_task(task_id, status="completed_with_errors", current_job_id=None)
        else:
            self.database.update_task(task_id, status="completed", current_job_id=None)
