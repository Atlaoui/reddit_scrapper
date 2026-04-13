"""Thin OpenRouter client wrapper: JSON output, cost logging, model tiers."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

log = logging.getLogger(__name__)

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "gemma3")

FAST_MODEL = DEFAULT_MODEL
SMART_MODEL = DEFAULT_MODEL

# Keep legacy names as aliases so existing callers (extract.py, cluster.py, synthesize.py)
# continue to import without changes.
HAIKU = FAST_MODEL
OPUS = SMART_MODEL

PRICING: dict[str, tuple[float, float]] = {}  # local models are free

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
        self.client = OpenAI(api_key="ollama", base_url=OLLAMA_BASE)
        self.total_usd = 0.0

    def _track(self, model: str, usage: Any) -> float:
        in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
        cost = (usage.prompt_tokens * in_rate + usage.completion_tokens * out_rate) / 1_000_000
        self.total_usd += cost
        return cost

    def call_json(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 4096,
    ) -> tuple[Any, float]:
        """Single-turn call; return (parsed_json, usd_cost). Retries once if model returns prose."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        total_cost = 0.0

        for attempt in range(2):
            resp = self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                response_format={"type": "json_object"},
            )
            text = resp.choices[0].message.content or ""
            total_cost += self._track(model, resp.usage)
            try:
                return _extract_json(text), total_cost
            except Exception as e:
                if attempt == 0:
                    log.warning("JSON parse failed (attempt 1), retrying: %s", e)
                    messages += [
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": "Your response was not valid JSON. Reply with ONLY the JSON object, no prose, no markdown."},
                    ]
                else:
                    log.error("JSON parse failed after retry: %s\n---\n%s", e, text[:500])
                    raise
