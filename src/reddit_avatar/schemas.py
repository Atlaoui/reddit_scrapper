"""Pydantic schemas for posts, signals, avatars."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _coerce_to_list(v: Any) -> list:
    """Accept a string or None where a list is expected — local models often do this."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    return v

SignalKind = Literal["pain", "desire", "vocabulary", "demographic", "jtbd"]


class Comment(BaseModel):
    id: str
    body: str
    score: int = 0
    author: str | None = None


class Post(BaseModel):
    id: str
    subreddit: str
    title: str
    body: str = ""
    author: str | None = None
    score: int = 0
    url: str
    created_utc: float
    comments: list[Comment] = Field(default_factory=list)


class Quote(BaseModel):
    text: str
    post_id: str


class ExtractedSignals(BaseModel):
    """Output shape required from the extraction LLM call."""

    pains: list[str] = Field(default_factory=list)
    desires: list[str] = Field(default_factory=list)
    vocabulary: list[str] = Field(default_factory=list)
    demographic_tells: list[str] = Field(default_factory=list)
    jtbd: list[str] = Field(default_factory=list)
    verbatim_quotes: list[Quote] = Field(default_factory=list)

    _coerce = field_validator(
        "pains", "desires", "vocabulary", "demographic_tells", "jtbd", mode="before"
    )(classmethod(lambda cls, v: _coerce_to_list(v)))


class AvatarStub(BaseModel):
    """Output of the clustering step."""

    name: str
    thesis: str
    signal_ids: list[int]


class ClusterResult(BaseModel):
    n_justification: str
    avatars: list[AvatarStub]


class AvatarProfile(BaseModel):
    """Full avatar synthesis — each bullet must carry post_id citations."""

    name: str
    thesis: str
    demographics: list[str]
    pains: list[str]
    desires: list[str]
    jtbd: list[str]
    vocabulary: list[str]
    beliefs: list[str]
    representative_quotes: list[Quote] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)

    _coerce = field_validator(
        "demographics", "pains", "desires", "jtbd", "vocabulary", "beliefs", "citations",
        mode="before",
    )(classmethod(lambda cls, v: _coerce_to_list(v)))


class Report(BaseModel):
    topic: str
    subreddits: list[str]
    generated_at: str
    run_id: int
    post_count: int
    signal_count: int
    cost_usd: float
    avatars: list[AvatarProfile]
    cluster_justification: str
