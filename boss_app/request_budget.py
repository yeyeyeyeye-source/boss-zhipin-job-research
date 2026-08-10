"""Persistent logical BOSS request budget for one Strategy Run."""

from __future__ import annotations

from .db import Database


class RequestBudgetExhausted(RuntimeError):
    """Raised before a BOSS operation when a Run has no remaining allowance."""


class RunRequestBudget:
    def __init__(self, database: Database, run_id: str):
        self.database = database
        self.run_id = run_id

    def reserve(self, request_kind: str) -> None:
        if self.database.reserve_run_request(self.run_id):
            return
        run = self.database.get_run(self.run_id)
        if run is None:
            raise KeyError(self.run_id)
        used = int(run["request_used"])
        limit = int(run["request_limit"])
        if used >= limit:
            raise RequestBudgetExhausted(
                f"Run 请求预算已耗尽: {used}/{limit}; 下一操作={request_kind}"
            )
        raise RuntimeError(
            f"Run {self.run_id} 当前状态 {run['status']}，不能预留 BOSS 请求"
        )
