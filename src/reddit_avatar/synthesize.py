"""Per-avatar profile synthesis via Opus — every claim cites post_ids."""
from __future__ import annotations

import json

from .llm import LLM, OPUS, load_prompt
from .schemas import AvatarProfile, AvatarStub, ClusterResult
from .store import Store


def synthesize(
    run_id: int, store: Store, llm: LLM, cluster_result: ClusterResult
) -> list[AvatarProfile]:
    system, _ = load_prompt("synthesize_avatar.md")
    records = {sid: (pid, sig) for sid, pid, sig in store.signals_for_run(run_id)}

    profiles: list[AvatarProfile] = []
    for stub in cluster_result.avatars:
        payload = _build_user_payload(stub, records)
        raw, cost = llm.call_json(model=OPUS, system=system, user=payload, max_tokens=4096)
        store.add_cost(run_id, cost)
        profile = AvatarProfile.model_validate(raw)
        store.save_avatar(
            run_id=run_id,
            name=profile.name,
            thesis=profile.thesis,
            signal_ids=stub.signal_ids,
            profile_json=profile.model_dump_json(),
        )
        profiles.append(profile)
    return profiles


def _build_user_payload(stub: AvatarStub, records: dict) -> str:
    signals_payload = []
    quotes_payload = []
    for sid in stub.signal_ids:
        if sid not in records:
            continue
        pid, sig = records[sid]
        signals_payload.append({
            "signal_id": sid, "post_id": pid,
            "pains": sig.pains, "desires": sig.desires,
            "vocabulary": sig.vocabulary,
            "demographic_tells": sig.demographic_tells,
            "jtbd": sig.jtbd,
        })
        for q in sig.verbatim_quotes:
            quotes_payload.append({"text": q.text, "post_id": q.post_id})

    return (
        f"AVATAR STUB:\nname: {stub.name}\nthesis: {stub.thesis}\n\n"
        f"SIGNALS:\n{json.dumps(signals_payload, indent=2)}\n\n"
        f"QUOTES:\n{json.dumps(quotes_payload, indent=2)}"
    )
