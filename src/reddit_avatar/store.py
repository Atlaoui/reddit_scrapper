"""SQLite store for posts, comments, signals, avatars, runs."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .schemas import Comment, ExtractedSignals, Post

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT    NOT NULL,
    config_hash TEXT    NOT NULL,
    started_at  REAL    NOT NULL,
    finished_at REAL,
    cost_usd    REAL    DEFAULT 0,
    status      TEXT    DEFAULT 'running'
);
CREATE TABLE IF NOT EXISTS posts (
    id          TEXT PRIMARY KEY,
    subreddit   TEXT,
    title       TEXT,
    body        TEXT,
    author      TEXT,
    score       INTEGER,
    url         TEXT,
    created_utc REAL,
    fetched_at  REAL
);
CREATE TABLE IF NOT EXISTS comments (
    id       TEXT PRIMARY KEY,
    post_id  TEXT NOT NULL,
    body     TEXT,
    score    INTEGER,
    author   TEXT,
    FOREIGN KEY(post_id) REFERENCES posts(id)
);
CREATE TABLE IF NOT EXISTS signals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id        TEXT    NOT NULL,
    run_id         INTEGER NOT NULL,
    payload_json   TEXT    NOT NULL,
    prompt_version TEXT    NOT NULL,
    created_at     REAL    NOT NULL,
    UNIQUE(post_id, prompt_version)
);
CREATE TABLE IF NOT EXISTS avatars (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL,
    name             TEXT,
    thesis           TEXT,
    signal_ids_json  TEXT,
    profile_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_run ON signals(run_id);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
"""


class Store:
    def __init__(self, db_path: str | Path = "data/signals.db"):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --- runs ---
    def start_run(self, topic: str, config_hash: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (topic, config_hash, started_at) VALUES (?, ?, ?)",
            (topic, config_hash, time.time()),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def finish_run(self, run_id: int, status: str = "ok") -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, status = ? WHERE id = ?",
            (time.time(), status, run_id),
        )
        self.conn.commit()

    def add_cost(self, run_id: int, usd: float) -> None:
        self.conn.execute(
            "UPDATE runs SET cost_usd = cost_usd + ? WHERE id = ?", (usd, run_id)
        )
        self.conn.commit()

    def run_cost(self, run_id: int) -> float:
        row = self.conn.execute(
            "SELECT cost_usd FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        return float(row["cost_usd"]) if row else 0.0

    # --- posts / comments ---
    def upsert_post(self, post: Post) -> None:
        self.conn.execute(
            """INSERT INTO posts
               (id, subreddit, title, body, author, score, url, created_utc, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                   score = excluded.score,
                   fetched_at = excluded.fetched_at""",
            (
                post.id, post.subreddit, post.title, post.body, post.author,
                post.score, post.url, post.created_utc, time.time(),
            ),
        )
        for c in post.comments:
            self.conn.execute(
                """INSERT OR REPLACE INTO comments (id, post_id, body, score, author)
                   VALUES (?,?,?,?,?)""",
                (c.id, post.id, c.body, c.score, c.author),
            )
        self.conn.commit()

    def post_ids(self) -> list[str]:
        return [r["id"] for r in self.conn.execute("SELECT id FROM posts")]

    def get_post(self, post_id: str) -> Post | None:
        row = self.conn.execute(
            "SELECT * FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        if not row:
            return None
        comments = [
            Comment(id=c["id"], body=c["body"], score=c["score"], author=c["author"])
            for c in self.conn.execute(
                "SELECT * FROM comments WHERE post_id = ?", (post_id,)
            )
        ]
        return Post(
            id=row["id"], subreddit=row["subreddit"], title=row["title"],
            body=row["body"] or "", author=row["author"], score=row["score"],
            url=row["url"], created_utc=row["created_utc"], comments=comments,
        )

    # --- signals ---
    def has_signal(self, post_id: str, prompt_version: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM signals WHERE post_id = ? AND prompt_version = ?",
            (post_id, prompt_version),
        ).fetchone()
        return row is not None

    def save_signal(
        self, post_id: str, run_id: int, signals: ExtractedSignals, prompt_version: str
    ) -> int:
        cur = self.conn.execute(
            """INSERT OR REPLACE INTO signals
               (post_id, run_id, payload_json, prompt_version, created_at)
               VALUES (?,?,?,?,?)""",
            (post_id, run_id, signals.model_dump_json(), prompt_version, time.time()),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def signals_for_run(self, run_id: int) -> list[tuple[int, str, ExtractedSignals]]:
        rows = self.conn.execute(
            "SELECT id, post_id, payload_json FROM signals WHERE run_id = ?", (run_id,)
        ).fetchall()
        return [
            (r["id"], r["post_id"], ExtractedSignals.model_validate_json(r["payload_json"]))
            for r in rows
        ]

    # --- avatars ---
    def save_avatar(
        self, run_id: int, name: str, thesis: str,
        signal_ids: list[int], profile_json: str,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO avatars (run_id, name, thesis, signal_ids_json, profile_json)
               VALUES (?,?,?,?,?)""",
            (run_id, name, thesis, json.dumps(signal_ids), profile_json),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def close(self) -> None:
        self.conn.close()
