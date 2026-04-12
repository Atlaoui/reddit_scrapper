"""Citation lint: every bullet should cite a post_id that exists in the store."""
from __future__ import annotations

import re
from pathlib import Path

from .store import Store

CITE_RE = re.compile(r"\[([a-z0-9_,\s]+)\]")
BULLET_RE = re.compile(r"^\s*-\s+(.*)$", re.MULTILINE)


def lint_file(path: str | Path, store: Store, threshold: float = 0.80) -> dict:
    """Return {bullets, cited, valid_refs, rate, ok}. Quote-ish bullets only — skips headers."""
    text = Path(path).read_text(encoding="utf-8")
    # Strip frontmatter so we don't lint the YAML subreddit list.
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:]

    bullets = [b.strip() for b in BULLET_RE.findall(text) if b.strip()]
    # Only lint substantive bullets (> 15 chars); skip the citation-dump list.
    claim_bullets = [b for b in bullets if len(b) > 15 and not b.startswith("[")]

    known = set(store.post_ids())
    cited = 0
    valid = 0
    for b in claim_bullets:
        m = CITE_RE.search(b)
        if not m:
            continue
        cited += 1
        ids = [x.strip() for x in m.group(1).split(",") if x.strip()]
        if any(pid in known for pid in ids):
            valid += 1

    total = len(claim_bullets) or 1
    rate = cited / total
    return {
        "bullets": len(claim_bullets),
        "cited": cited,
        "valid_refs": valid,
        "rate": rate,
        "ok": rate >= threshold,
    }
