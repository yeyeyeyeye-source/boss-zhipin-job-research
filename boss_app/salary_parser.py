"""Salary text parsing without unit conversion or inference."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SalaryParts:
    raw: str
    salary_range: str
    salary_months: str


_SALARY_MONTHS_RE = re.compile(r"^(?P<range>.+?)[·・]\s*(?P<months>\d{1,2}薪)\s*$")


def parse_salary(raw: str | None) -> SalaryParts:
    """Split an explicit ``·N薪`` suffix while preserving the source text."""
    value = str(raw or "").strip()
    if not value:
        return SalaryParts(raw="", salary_range="未注明", salary_months="未注明")
    match = _SALARY_MONTHS_RE.match(value)
    if not match:
        return SalaryParts(raw=value, salary_range=value, salary_months="未注明")
    return SalaryParts(
        raw=value,
        salary_range=match.group("range").strip(),
        salary_months=match.group("months"),
    )
