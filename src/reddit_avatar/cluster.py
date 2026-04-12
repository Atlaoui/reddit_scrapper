"""Cluster per-post signals into N avatar stubs using Opus."""
from __future__ import annotations

import json
from typing import Any

from .llm import LLM, OPUS, load_prompt
from .schemas import ClusterResult
from .store import Store


def _signal_payload(records: list[tuple[int, str, Any]]) -> str:
    out = []
    for sid, pid, sig in records:
        out.append({
            "signal_id": sid,
            "post_id": pid,
            "pains": sig.pains,
            "desires": sig.desires,
            "vocabulary": sig.vocabulary,
            "demographic_tells": sig.demographic_tells,
            "jtbd": sig.jtbd,
        })
    return json.dumps(out, indent=2)


def cluster(run_id: int, store: Store, llm: LLM, target_count: int | None) -> ClusterResult:
    system, _ = load_prompt("cluster_avatars.md")
    records = store.signals_for_run(run_id)
    if not records:
        raise RuntimeError("no signals to cluster — run extract first")
    user = (
        f"Target N: {target_count if target_count is not None else 'null (auto)'}\n\n"
        f"SIGNALS:\n{_signal_payload(records)}"
    )
    raw, cost = llm.call_json(model=OPUS, system=system, user=user, max_tokens=4096)
    store.add_cost(run_id, cost)
    return ClusterResult.model_validate(raw)
