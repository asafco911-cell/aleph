"""Content-addressed cache for LLM calls.

Caching here is about reproducibility before cost: without it, the same filing
yields different numbers on different days and a track record becomes noise
with timestamps. The key therefore includes every input that can change an
answer - document bytes, prompt version, model, target, and question. A
partial key is worse than no cache, because it returns a stale answer that
looks current.
"""
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATH = Path("data/aleph_cache.db")


class Cache:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS entries ("
                "  key TEXT PRIMARY KEY,"
                "  payload TEXT NOT NULL,"
                "  created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )

    @staticmethod
    def key(**parts: Any) -> str:
        """Order-independent key over every input that can change the answer."""
        canonical = json.dumps(parts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[dict]:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT payload FROM entries WHERE key = ?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, payload: dict) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO entries (key, payload) VALUES (?, ?)",
                (key, json.dumps(payload, ensure_ascii=False)),
            )