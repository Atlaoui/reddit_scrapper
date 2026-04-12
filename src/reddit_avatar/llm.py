"""Thin Anthropic client wrapper: JSON output, cost logging, model tiers."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from anthropic import Anthropic

log = logging.getLogger(__name__)

HAIKU = "claude-haiku-4-5-20251001"
OPUS = "claude-opus-4-6"

# Rough USD per 1M tokens (input, output). Update if Anthropic pricing shifts.
PRICING: dict[str, tuple[float, float]] = {
    HAIKU: (1.00, 5.00),
    OPUS: (15.00, 75.00),
}

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def load_prompt(name: str) -> tuple[str, str]:
    """Return (prompt_text, version_hash)."""
    text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    version = hashlib.sha256(text.encode()).hexdigest()[:12]
    return text, version


def _extract_json(text: str) -> Any:
    """Pull JSON out of an LLM response — tolerates ```json fences and prose."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1).strip())
    # Fall back to first {...} or [...] block.
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    return json.loads(text)


class LLM:
    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self.client = Anthropic(api_key=key)
        self.total_usd = 0.0

    def _track(self, model: str, usage: Any) -> float:
        in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
        cost = (usage.input_tokens * in_rate + usage.output_tokens * out_rate) / 1_000_000
        self.total_usd += cost
        return cost

    def call_json(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 4096,
    ) -> tuple[Any, float]:
        """Single-turn call; return (parsed_json, usd_cost)."""
        resp = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        cost = self._track(model, resp.usage)
        try:
            return _extract_json(text), cost
        except Exception as e:
            log.error("JSON parse failed: %s\n---\n%s", e, text[:500])
            raise
