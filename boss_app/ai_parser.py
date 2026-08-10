"""OpenAI-compatible semantic JD parser with strict local validation."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from .job_type_parser import JOB_TYPES, normalize_job_type

try:
    import requests as _requests
except ImportError:
    _requests = None

REQUEST_EXCEPTIONS = (OSError, TimeoutError, RuntimeError)
if _requests is not None:
    REQUEST_EXCEPTIONS += (_requests.RequestException,)


class AIParseError(RuntimeError):
    """Raised after an AI response cannot be obtained or validated."""


@dataclass(frozen=True)
class AIConfig:
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout: float = 60.0
    max_retries: int = 2

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    @classmethod
    def from_env(cls, env_file: str | None = None) -> "AIConfig":
        try:
            from dotenv import load_dotenv

            load_dotenv(env_file, override=False)
        except ImportError:
            pass
        return cls(
            api_key=os.environ.get("BOSS_AI_API_KEY", "").strip(),
            base_url=os.environ.get("BOSS_AI_BASE_URL", "").strip(),
            model=os.environ.get("BOSS_AI_MODEL", "").strip(),
            timeout=float(os.environ.get("BOSS_AI_TIMEOUT_SECONDS", "60")),
            max_retries=max(0, int(os.environ.get("BOSS_AI_MAX_RETRIES", "2"))),
        )


@dataclass(frozen=True)
class ParsedJD:
    is_ai_operations: bool
    job_type: str
    job_responsibilities: list[str]
    job_requirements: list[str]
    bonus_points: list[str]


@dataclass(frozen=True)
class TargetParsedJD:
    match_status: str
    role_category: str
    relevance_reason: str
    relevance_confidence: float
    job_type: str
    job_responsibilities: list[str]
    job_requirements: list[str]
    bonus_points: list[str]


EXPECTED_KEYS = {
    "is_ai_operations", "job_type", "job_responsibilities",
    "job_requirements", "bonus_points",
}
TARGET_EXPECTED_KEYS = {
    "match_status", "role_category", "relevance_reason", "relevance_confidence",
    "job_type", "job_responsibilities", "job_requirements", "bonus_points",
}
TARGET_MATCH_STATUSES = {"matched", "manual_review", "irrelevant"}


def _clean_items(value: Any, field: str, fallback: str = "未注明") -> list[str]:
    if not isinstance(value, list):
        raise AIParseError(f"AI 字段 {field} 必须是数组")
    items: list[str] = []
    seen = set()
    for raw in value:
        if not isinstance(raw, str):
            raise AIParseError(f"AI 字段 {field} 只能包含字符串")
        item = raw.strip()
        if item and item not in seen:
            items.append(item)
            seen.add(item)
    return items or [fallback]


def validate_payload(payload: Any, explicit_job_type: str = "未注明") -> ParsedJD:
    if not isinstance(payload, dict):
        raise AIParseError("AI 响应必须是 JSON 对象")
    if set(payload) != EXPECTED_KEYS:
        missing = EXPECTED_KEYS - set(payload)
        extra = set(payload) - EXPECTED_KEYS
        raise AIParseError(f"AI JSON 字段不匹配，缺少={sorted(missing)}，多余={sorted(extra)}")
    if type(payload["is_ai_operations"]) is not bool:
        raise AIParseError("AI 字段 is_ai_operations 必须是布尔值")
    raw_type = str(payload.get("job_type") or "").strip()
    if raw_type not in JOB_TYPES:
        raise AIParseError(f"未知岗位类型: {raw_type}")
    job_type = explicit_job_type if explicit_job_type != "未注明" else normalize_job_type(ai_value=raw_type)
    return ParsedJD(
        is_ai_operations=payload["is_ai_operations"],
        job_type=job_type,
        job_responsibilities=_clean_items(payload["job_responsibilities"], "job_responsibilities"),
        job_requirements=_clean_items(payload["job_requirements"], "job_requirements"),
        bonus_points=_clean_items(payload["bonus_points"], "bonus_points", "无"),
    )


def validate_target_payload(
    payload: Any, explicit_job_type: str = "未注明",
) -> TargetParsedJD:
    if not isinstance(payload, dict) or set(payload) != TARGET_EXPECTED_KEYS:
        raise AIParseError("AI 目标岗位 JSON 字段不匹配")
    status = str(payload["match_status"] or "").strip()
    if status not in TARGET_MATCH_STATUSES:
        raise AIParseError(f"未知目标岗位匹配状态: {status}")
    reason = str(payload["relevance_reason"] or "").strip()
    if not reason:
        raise AIParseError("AI 相关性理由不能为空")
    confidence = payload["relevance_confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise AIParseError("AI 相关性置信度必须是数字")
    if not 0 <= float(confidence) <= 1:
        raise AIParseError("AI 相关性置信度必须在 0 到 1 之间")
    raw_type = str(payload["job_type"] or "").strip()
    if raw_type not in JOB_TYPES:
        raise AIParseError(f"未知岗位类型: {raw_type}")
    job_type = explicit_job_type if explicit_job_type != "未注明" else normalize_job_type(ai_value=raw_type)
    return TargetParsedJD(
        match_status=status,
        role_category=str(payload["role_category"] or "未分类").strip() or "未分类",
        relevance_reason=reason,
        relevance_confidence=float(confidence),
        job_type=job_type,
        job_responsibilities=_clean_items(payload["job_responsibilities"], "job_responsibilities"),
        job_requirements=_clean_items(payload["job_requirements"], "job_requirements"),
        bonus_points=_clean_items(payload["bonus_points"], "bonus_points", "无"),
    )


def _parse_json_content(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AIParseError("AI 响应不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise AIParseError("AI 响应必须是 JSON 对象")
    return payload


SYSTEM_PROMPT = """你是 AI 运营岗位审核与 JD 信息整理器。只能依据用户提供的原始完整 JD，禁止补充、推测或写入行业常见要求。
返回且仅返回 JSON 对象，必须包含 is_ai_operations、job_type、job_responsibilities、job_requirements、bonus_points 五个键。
is_ai_operations 只能是 JSON 布尔值。只有岗位职责核心是运营，且 AI 是实际工作对象、生产工具或运营流程的重要组成部分时为 true。
销售 AI 产品、CIO、纯产品经理、人工智能训练师，以及只在任职要求或公司介绍中提到 AI 的岗位为 false。
job_type 只能是：实习、全职、兼职、校招、劳务/外包、其他、未注明。
其余三个字段必须是字符串数组；职责或要求没有原文证据时数组为 [\"未注明\"]，没有加分项时 bonus_points 为 [\"无\"]。
岗位职责只放工作任务；任职要求只放强制或基础条件；加分项只放优先、加分或非强制条件。
每一项使用简洁中文短语，可以删除完全重复内容，但不得改造成原文没有的新要求。"""

TARGET_SYSTEM_PROMPT = """你是目标岗位审核与 JD 信息整理器。严格遵循用户确认的唯一目标，只能依据岗位标题、页面标签和原始完整 JD 判断，不得扩展、替换或改写用户目标。
exact_role 要求岗位核心职责同时符合目标领域和具体职能；domain_scope 允许目标领域内的不同职能，但岗位核心职责必须直接服务该领域。公司介绍、任职要求或工具列表中偶然出现目标词不能作为相关证据。证据不足、职责边界冲突或无法可靠判断时使用 manual_review。
返回且仅返回 JSON 对象，必须包含 match_status、role_category、relevance_reason、relevance_confidence、job_type、job_responsibilities、job_requirements、bonus_points 八个键。
match_status 只能是 matched、manual_review、irrelevant；relevance_reason 必须简短引用 JD 证据；relevance_confidence 是 0 到 1 的数字。
job_type 只能是：实习、全职、兼职、校招、劳务/外包、其他、未注明。其余三个信息字段必须是字符串数组；没有原文证据时使用 ["未注明"]，没有加分项时使用 ["无"]。"""


class JDParser:
    def __init__(self, config: AIConfig | None = None, session: Any = None, sleep_fn=time.sleep):
        self.config = config or AIConfig.from_env()
        self.session = session
        self.sleep_fn = sleep_fn

    def _endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    def parse(self, full_jd: str, context: dict[str, Any] | None = None) -> ParsedJD:
        jd = str(full_jd or "").strip()
        if not jd:
            raise ValueError("完整 JD 为空，禁止调用 AI")
        if not self.config.configured:
            raise AIParseError("AI 配置不完整")
        context = context or {}
        explicit_type = normalize_job_type(
            title=str(context.get("job_name") or context.get("title") or ""),
            labels=str(context.get("labels") or ""),
        )
        if self.session is None:
            if _requests is None:
                raise AIParseError("缺少 requests 依赖")
            self.session = _requests.Session()

        request_payload = {
            "model": self.config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "岗位名称": context.get("job_name") or context.get("title") or "",
                            "页面标签": context.get("labels") or "",
                            "完整JD": jd,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.post(
                    self._endpoint(), headers=headers, json=request_payload,
                    timeout=self.config.timeout,
                )
                response.raise_for_status()
                envelope = response.json()
                content = envelope["choices"][0]["message"]["content"]
                return validate_payload(_parse_json_content(content), explicit_type)
            except (AIParseError, KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = exc
            except REQUEST_EXCEPTIONS as exc:
                last_error = exc
            if attempt < self.config.max_retries:
                self.sleep_fn(min(2 ** attempt, 8))
        raise AIParseError(f"AI 解析失败: {last_error}") from last_error

    def parse_target(
        self,
        full_jd: str,
        *,
        target_role: str,
        target_type: str,
        context: dict[str, Any] | None = None,
    ) -> TargetParsedJD:
        jd = str(full_jd or "").strip()
        target = str(target_role or "").strip()
        if not jd:
            raise ValueError("完整 JD 为空，禁止调用 AI")
        if not target:
            raise ValueError("用户确认目标不能为空")
        if target_type not in {"exact_role", "domain_scope"}:
            raise ValueError(f"未知目标类型: {target_type}")
        if not self.config.configured:
            raise AIParseError("AI 配置不完整")
        context = context or {}
        explicit_type = normalize_job_type(
            title=str(context.get("job_name") or context.get("title") or ""),
            labels=str(context.get("labels") or ""),
        )
        if self.session is None:
            if _requests is None:
                raise AIParseError("缺少 requests 依赖")
            self.session = _requests.Session()
        request_payload = {
            "model": self.config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": TARGET_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "用户确认目标": target,
                            "目标类型": target_type,
                            "岗位名称": context.get("job_name") or context.get("title") or "",
                            "页面标签": context.get("labels") or "",
                            "完整JD": jd,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.post(
                    self._endpoint(), headers=headers, json=request_payload,
                    timeout=self.config.timeout,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return validate_target_payload(_parse_json_content(content), explicit_type)
            except (AIParseError, KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = exc
            except REQUEST_EXCEPTIONS as exc:
                last_error = exc
            if attempt < self.config.max_retries:
                self.sleep_fn(min(2 ** attempt, 8))
        raise AIParseError(f"AI 目标岗位解析失败: {last_error}") from last_error
