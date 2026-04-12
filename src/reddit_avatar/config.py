"""Topic config loader."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class Limits(BaseModel):
    posts_per_sub: int = 200
    comments_per_post: int = 20
    time_window: Literal["hour", "day", "week", "month", "year", "all"] = "year"
    max_usd: float = 5.0


class AvatarsCfg(BaseModel):
    target_count: int | None = None  # None = auto-justify 1–4


class OutputCfg(BaseModel):
    path: str = "output/avatars/"


class TopicConfig(BaseModel):
    topic: str
    subreddits: list[str]
    search_queries: list[str] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    avatars: AvatarsCfg = Field(default_factory=AvatarsCfg)
    output: OutputCfg = Field(default_factory=OutputCfg)

    @classmethod
    def load(cls, path: str | Path) -> "TopicConfig":
        raw = Path(path).read_text(encoding="utf-8")
        return cls.model_validate(yaml.safe_load(raw))

    def fingerprint(self) -> str:
        """Stable hash of config — goes into run record."""
        payload = self.model_dump_json().encode()
        return hashlib.sha256(payload).hexdigest()[:16]
