"""Typed MCP schemas; store validators remain the authoritative wire contract."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ActivityRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    event_id: str
    skill: str
    subject: str
    action: str
    state: Literal['planned', 'drafted', 'scheduled', 'completed', 'published', 'failed', 'cancelled', 'unknown', 'observed']
    summary: str
    occurred_at: str
    source: str
    source_id: str
    details: str = ''
    artifacts: list[str] = Field(default_factory=list)
    evidence_kind: Literal['agent-report', 'source-log', 'tool-result'] = 'agent-report'


class SkillRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    contract: Literal['skill-memory-v1']
    skill: str
    subject: str
    op: Literal['status', 'recall', 'capture', 'inspect', 'forget']
    keys: list[str] | None = None
    key: str | None = None
    value: dict | str | list | bool | int | float | None = None
    capture_id: str | None = None
    source: str | None = None
    id: str | None = None
    expected_revision: str | None = None
    review_after: str | None = None
    supersedes: str | None = None
    dependencies: list[dict] | None = None
    expected_source_revision: str | None = None
    max_context_bytes: int | None = None
