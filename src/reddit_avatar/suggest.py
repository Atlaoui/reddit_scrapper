"""LLM-powered subreddit discovery from a free-text research demand."""
from __future__ import annotations

from pydantic import BaseModel

from .llm import FAST_MODEL, LLM, load_prompt


class SuggestionResult(BaseModel):
    topic: str
    subreddits: list[str]
    search_queries: list[str]


def suggest_subreddits(demand: str, llm: LLM) -> SuggestionResult:
    """Ask the LLM to recommend subreddits and search queries for a research demand."""
    system, _ = load_prompt("suggest_subreddits.md")
    data, _ = llm.call_json(FAST_MODEL, system, demand)
    return SuggestionResult.model_validate(data)
