"""Conservative job-type normalization using only explicit source evidence."""

from __future__ import annotations

JOB_TYPES = ("实习", "全职", "兼职", "校招", "劳务/外包", "其他", "未注明")


def normalize_job_type(
    title: str = "",
    labels: str = "",
    jd: str = "",
    ai_value: str | None = None,
) -> str:
    """Return a fixed enum; explicit page signals take precedence over AI."""
    explicit = " ".join((str(title or ""), str(labels or "")))
    if any(token in explicit for token in ("外包", "劳务", "派遣")):
        return "劳务/外包"
    if "兼职" in explicit:
        return "兼职"
    if "实习" in explicit:
        return "实习"
    if any(token in explicit for token in ("校招", "校园招聘")):
        return "校招"
    if "全职" in explicit:
        return "全职"

    normalized_ai = str(ai_value or "").strip()
    if normalized_ai in JOB_TYPES:
        return normalized_ai

    # Full JD is intentionally not classified with keywords. It is passed to
    # the semantic parser, avoiding false positives such as “应届生可投”.
    _ = jd
    return "未注明"
