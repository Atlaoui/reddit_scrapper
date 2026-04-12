"""Per-post signal extraction via Haiku."""
from __future__ import annotations

import logging

from .llm import HAIKU, LLM, load_prompt
from .schemas import ExtractedSignals, Post
from .store import Store

log = logging.getLogger(__name__)

MAX_BODY_CHARS = 4000
MAX_COMMENT_CHARS = 400
MAX_COMMENTS = 15


def _format_post(post: Post) -> str:
    body = (post.body or "")[:MAX_BODY_CHARS]
    parts = [
        f"POST_ID: {post.id}",
        f"SUBREDDIT: r/{post.subreddit}",
        f"TITLE: {post.title}",
        f"BODY:\n{body}" if body else "BODY: (link post, no text)",
    ]
    if post.comments:
        comments = "\n".join(
            f"- (score={c.score}) {c.body[:MAX_COMMENT_CHARS]}"
            for c in post.comments[:MAX_COMMENTS] if c.body
        )
        parts.append(f"TOP COMMENTS:\n{comments}")
    return "\n\n".join(parts)


def extract_all(run_id: int, store: Store, llm: LLM) -> int:
    """Extract signals for every stored post not yet processed. Returns # extracted."""
    system, version = load_prompt("extract_signals.md")
    processed = 0
    for pid in store.post_ids():
        if store.has_signal(pid, version):
            continue
        post = store.get_post(pid)
        if not post:
            continue
        try:
            raw, cost = llm.call_json(
                model=HAIKU, system=system, user=_format_post(post), max_tokens=2048
            )
            store.add_cost(run_id, cost)
            signals = ExtractedSignals.model_validate(raw)
            store.save_signal(pid, run_id, signals, version)
            processed += 1
        except Exception as e:
            log.warning("extract failed for %s: %s", pid, e)
    return processed
