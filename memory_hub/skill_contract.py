"""Small deterministic skill-memory protocol; no network or model dependencies."""

from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

CONTRACT = "skill-memory-v1"
CATALOG = Path(__file__).with_name("skill_catalog.json")
TEXT_LIMITS = {
    "writing.hashtags": 512,
    "writing-x.hashtags": 512,
    "devlog.audience": 256,
    "issue.acceptance-style": 256,
    "project.design-rationale": 2048,
    "project.known-constraint": 1024,
    "workflow.design-rationale": 1024,
    "study.handout-format": 128,
    "city-report.layout": 128,
    "resume.presentation-format": 128,
    "shipreport.audience": 256,
    "shipreport.emphasis": 256,
    "skill-design.interaction-style": 256,
    "skill-design.output-format": 128,
}
RATIONALE = {
    "project.design-rationale",
    "project.known-constraint",
    "workflow.design-rationale",
}


def digest(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else value.encode()
    ).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def policies():
    return json.loads(CATALOG.read_text())["skills"]


def validate_value(skill, key, value, *, reading=False):
    policy = policies().get(skill)
    if not policy or policy["mode"] == "deferred":
        raise ValueError("SKILL_DISABLED")
    allowed = policy["keys"] + (policy["read_keys"] if reading else [])
    if key not in allowed:
        raise ValueError("KEY_NOT_ALLOWED")
    if key in TEXT_LIMITS:
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.encode()) > TEXT_LIMITS[key]
            or "\x00" in value
        ):
            raise ValueError("INVALID_VALUE")
    elif key.endswith("explanation-depth"):
        if value not in ("brief", "standard", "detailed") or not isinstance(value, str):
            raise ValueError("INVALID_VALUE")
    elif key == "study.duration-minutes":
        if type(value) is not int or not 5 <= value <= 240:
            raise ValueError("INVALID_VALUE")
    elif key == "city-report.metric-order":
        metrics = json.loads(CATALOG.read_text())["city_metrics"]
        if (
            not isinstance(value, list)
            or not 1 <= len(value) <= 22
            or any(not isinstance(x, str) or x not in metrics for x in value)
            or len(set(value)) != len(value)
        ):
            raise ValueError("INVALID_VALUE")
    else:
        raise ValueError("KEY_NOT_ALLOWED")
    # Deterministic supplemental screen, not a semantic privacy guarantee.
    if re.search(
        r"(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{20,}|-----BEGIN .*PRIVATE KEY-----",
        canonical(value),
    ):
        raise ValueError("SECRET_SHAPED_VALUE")
    return value
