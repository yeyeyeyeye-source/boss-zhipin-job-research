"""Immutable identity for one user-confirmed multi-city search strategy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


TARGET_TYPES = {"exact_role", "domain_scope"}


def _identity_text(value: str) -> str:
    return "".join(str(value or "").split()).casefold()


def _display_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


@dataclass(frozen=True)
class StrategySpec:
    search_keyword: str
    target_role: str
    target_type: str
    ordered_cities: tuple[str, ...]
    salary_filter: str = ""
    experience_filter: str = ""
    degree_filter: str = ""

    @classmethod
    def create(
        cls,
        search_keyword: str,
        target_role: str,
        target_type: str,
        cities: list[str] | tuple[str, ...],
        *,
        salary_filter: str = "",
        experience_filter: str = "",
        degree_filter: str = "",
    ) -> "StrategySpec":
        keyword = _display_text(search_keyword)
        target = _display_text(target_role)
        if not keyword:
            raise ValueError("检索词不能为空")
        if not target:
            raise ValueError("目标岗位不能为空")
        if target_type not in TARGET_TYPES:
            raise ValueError("目标类型必须是 exact_role 或 domain_scope")

        ordered = tuple(
            dict.fromkeys(
                _display_text(city) for city in cities if _display_text(city)
            )
        )
        if not ordered:
            raise ValueError("城市不能为空")

        return cls(
            search_keyword=keyword,
            target_role=target,
            target_type=target_type,
            ordered_cities=ordered,
            salary_filter=str(salary_filter or "").strip(),
            experience_filter=str(experience_filter or "").strip(),
            degree_filter=str(degree_filter or "").strip(),
        )

    @property
    def city_set(self) -> tuple[str, ...]:
        return tuple(sorted(self.ordered_cities, key=_identity_text))

    @property
    def filters(self) -> dict[str, str]:
        return {
            "salary": self.salary_filter,
            "experience": self.experience_filter,
            "degree": self.degree_filter,
        }

    @property
    def signature_payload(self) -> dict[str, object]:
        return {
            "search_keyword": _identity_text(self.search_keyword),
            "target_role": _identity_text(self.target_role),
            "target_type": self.target_type,
            "cities": [_identity_text(city) for city in self.city_set],
            "filters": {
                name: _identity_text(value)
                for name, value in self.filters.items()
            },
        }

    @property
    def signature(self) -> str:
        payload = json.dumps(
            self.signature_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
