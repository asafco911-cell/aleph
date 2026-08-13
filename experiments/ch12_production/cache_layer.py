"""Deterministic caching layer. Turns a probabilistic pipeline into a reproducible one."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional, Any

CACHE_DB = Path(__file__).parent / "aleph_cache.db"

# Approximate USD per million tokens - update as pricing changes
PRICING = {
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
}


def _init_db():
    """Create the cache and cost tables if they do not exist."""
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            created_at REAL NOT NULL,
            hit_count INTEGER DEFAULT 0
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cost_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            run_id TEXT,
            stage TEXT,
            model TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd REAL,
            was_cached INTEGER
        )""")
    conn.commit()
    conn.close()


def make_key(**components) -> str:
    """Build a cache key from EVERY input that affects the output.
    A partial key is worse than no cache - it returns wrong answers confidently."""
    canonical = json.dumps(components, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def cache_get(key: str) -> Optional[Any]:
    """Retrieve a cached value and increment its hit counter."""
    conn = sqlite3.connect(CACHE_DB)
    row = conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
    if row:
        conn.execute("UPDATE cache SET hit_count = hit_count + 1 WHERE key = ?", (key,))
        conn.commit()
    conn.close()
    return json.loads(row[0]) if row else None


def cache_set(key: str, value: Any) -> None:
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("INSERT OR REPLACE INTO cache (key, value, created_at) VALUES (?, ?, ?)",
                 (key, json.dumps(value, default=str), time.time()))
    conn.commit()
    conn.close()


_init_db()

def log_cost(run_id: str, stage: str, model: str,
             input_tokens: int, output_tokens: int, was_cached: bool) -> float:
    """Record the cost of one call. Cached calls cost zero but are still logged,
    so we can measure how much the cache saved."""
    if was_cached:
        cost = 0.0
    else:
        p = PRICING.get(model, {"input": 0, "output": 0})
        cost = (input_tokens / 1_000_000 * p["input"]
                + output_tokens / 1_000_000 * p["output"])

    conn = sqlite3.connect(CACHE_DB)
    conn.execute("""INSERT INTO cost_log
        (timestamp, run_id, stage, model, input_tokens, output_tokens, cost_usd, was_cached)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (time.time(), run_id, stage, model, input_tokens, output_tokens, cost, int(was_cached)))
    conn.commit()
    conn.close()
    return cost


def cost_report(run_id: Optional[str] = None) -> dict:
    """Break down spend by stage - shows WHERE the money goes, not just how much."""
    conn = sqlite3.connect(CACHE_DB)
    where = "WHERE run_id = ?" if run_id else ""
    params = (run_id,) if run_id else ()

    total = conn.execute(f"SELECT SUM(cost_usd) FROM cost_log {where}", params).fetchone()[0] or 0.0
    by_stage = conn.execute(
        f"""SELECT stage, COUNT(*), SUM(cost_usd), SUM(was_cached)
            FROM cost_log {where} GROUP BY stage ORDER BY SUM(cost_usd) DESC""",
        params).fetchall()
    conn.close()

    return {
        "total_usd": total,
        "by_stage": [{"stage": s, "calls": c, "cost": cost or 0.0, "cached": cached or 0}
                     for s, c, cost, cached in by_stage],
    }