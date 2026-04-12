"""Reddit .json harvester with on-disk caching + polite backoff."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import TopicConfig
from .schemas import Comment, Post
from .store import Store

log = logging.getLogger(__name__)

USER_AGENT = "reddit-avatar/0.1 (market research)"
BASE = "https://www.reddit.com"
REQUEST_DELAY_S = 2.0
CACHE_DIR = Path("data/cache")


def _cache_key(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.json"


@retry(
    retry=retry_if_exception_type((httpx.HTTPError,)),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _fetch(client: httpx.Client, url: str) -> dict[str, Any]:
    cache = _cache_key(url)
    if cache.exists():
        return json.loads(cache.read_text())
    log.info("GET %s", url)
    r = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    data = r.json()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data))
    time.sleep(REQUEST_DELAY_S)
    return data


def _parse_listing(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [c["data"] for c in data.get("data", {}).get("children", []) if c.get("kind") == "t3"]


def _parse_top_level_comments(data: Any, limit: int) -> list[Comment]:
    if not isinstance(data, list) or len(data) < 2:
        return []
    children = data[1].get("data", {}).get("children", [])
    out: list[Comment] = []
    for c in children:
        if c.get("kind") != "t1":
            break
        cd = c["data"]
        out.append(
            Comment(
                id=cd["id"],
                body=cd.get("body", ""),
                score=cd.get("score", 0),
                author=cd.get("author"),
            )
        )
        if len(out) >= limit:
            break
    return out


def _search_url(sub: str, query: str, window: str, limit: int) -> str:
    return (
        f"{BASE}/r/{sub}/search.json?"
        f"q={httpx.QueryParams({'q': query})['q']}"
        f"&restrict_sr=1&sort=relevance&t={window}&limit={min(limit, 100)}"
    )


def _listing_url(sub: str, window: str, limit: int) -> str:
    return f"{BASE}/r/{sub}/top.json?t={window}&limit={min(limit, 100)}"


def _comments_url(post_id: str, limit: int) -> str:
    return f"{BASE}/comments/{post_id}.json?limit={limit}&depth=1"


def harvest(cfg: TopicConfig, store: Store) -> int:
    """Scrape posts + top-level comments; upsert into store. Returns post count."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with httpx.Client(follow_redirects=True) as client:
        for sub in cfg.subreddits:
            urls = (
                [_search_url(sub, q, cfg.limits.time_window, cfg.limits.posts_per_sub)
                 for q in cfg.search_queries]
                if cfg.search_queries
                else [_listing_url(sub, cfg.limits.time_window, cfg.limits.posts_per_sub)]
            )
            for url in urls:
                try:
                    listing = _fetch(client, url)
                except httpx.HTTPError as e:
                    log.warning("listing failed %s: %s", url, e)
                    continue
                for pd in _parse_listing(listing):
                    pid = pd["id"]
                    if pid in seen:
                        continue
                    seen.add(pid)
                    try:
                        comment_data = _fetch(client, _comments_url(pid, cfg.limits.comments_per_post))
                        comments = _parse_top_level_comments(comment_data, cfg.limits.comments_per_post)
                    except httpx.HTTPError as e:
                        log.warning("comments failed for %s: %s", pid, e)
                        comments = []
                    post = Post(
                        id=pid,
                        subreddit=pd.get("subreddit", sub),
                        title=pd.get("title", ""),
                        body=pd.get("selftext", ""),
                        author=pd.get("author"),
                        score=pd.get("score", 0),
                        url=BASE + pd.get("permalink", ""),
                        created_utc=pd.get("created_utc", 0.0),
                        comments=comments,
                    )
                    store.upsert_post(post)
    return len(seen)
