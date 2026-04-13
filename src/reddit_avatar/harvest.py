"""Reddit .json harvester — Selenium-based to bypass 403s, with on-disk caching."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from .config import TopicConfig
from .schemas import Comment, Post
from .store import Store

log = logging.getLogger(__name__)

BASE = "https://www.reddit.com"
REQUEST_DELAY_S = 3.0
CACHE_DIR = Path("data/cache")


def _cache_key(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.json"


def _make_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


def _fetch(driver: webdriver.Chrome, url: str) -> Any:
    cache = _cache_key(url)
    if cache.exists():
        return json.loads(cache.read_text())
    log.info("GET %s", url)
    driver.get(url)
    time.sleep(REQUEST_DELAY_S)
    # The browser renders JSON as plain text inside a <pre> or directly as body text
    body = driver.find_element("tag name", "body").text
    if not body.strip():
        return {}
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        log.warning("could not parse JSON from %s", url)
        return {}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data))
    return data


def _parse_listing(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
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


def _listing_url(sub: str, window: str, limit: int) -> str:
    return f"{BASE}/r/{sub}/top.json?t={window}&limit={min(limit, 100)}"


def _search_url(sub: str, query: str, window: str, limit: int) -> str:
    from urllib.parse import quote_plus
    q = quote_plus(query)
    return f"{BASE}/r/{sub}/search.json?q={q}&restrict_sr=1&sort=relevance&t={window}&limit={min(limit, 100)}"


def _comments_url(post_id: str, limit: int) -> str:
    return f"{BASE}/comments/{post_id}.json?limit={limit}&depth=1"


def harvest(cfg: TopicConfig, store: Store) -> int:
    """Scrape posts + top-level comments via Selenium; upsert into store. Returns post count."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()

    log.info("Starting headless Chrome…")
    driver = _make_driver()
    try:
        for sub in cfg.subreddits:
            urls = (
                [_search_url(sub, q, cfg.limits.time_window, cfg.limits.posts_per_sub)
                 for q in cfg.search_queries]
                if cfg.search_queries
                else [_listing_url(sub, cfg.limits.time_window, cfg.limits.posts_per_sub)]
            )
            for url in urls:
                listing = _fetch(driver, url)
                for pd in _parse_listing(listing):
                    pid = pd["id"]
                    if pid in seen:
                        continue
                    seen.add(pid)
                    comment_data = _fetch(driver, _comments_url(pid, cfg.limits.comments_per_post))
                    comments = _parse_top_level_comments(comment_data, cfg.limits.comments_per_post)
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
    finally:
        driver.quit()

    return len(seen)
