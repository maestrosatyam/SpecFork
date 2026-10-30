"""Run store (memory, optionally backed by SQLite), change notification, capability tokens and abuse controls."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RunStore:
    """Keeps runs in memory; with ``db_path`` every finished step is also written to SQLite so runs survive a
    restart and several server processes on one host can read each other's runs."""

    def __init__(self, db_path: str | None = None, max_runs: int = 300) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, int] = defaultdict(int)
        self.events: dict[str, asyncio.Event] = {}
        self.tokens: dict[str, str] = {}  # run id -> sha256(token)
        self.max_runs = max_runs
        self.db: sqlite3.Connection | None = None
        if db_path:
            try:
                self.db = sqlite3.connect(db_path, check_same_thread=False)
                self.db.execute("PRAGMA user_version")
            except sqlite3.Error as e:  # unwritable location: keep serving from memory
                import logging

                logging.getLogger("specfork").warning("run store %s unavailable (%s); using memory only", db_path, e)
                self.db = None
        if self.db is not None:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at REAL, json TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS tokens (run_id TEXT PRIMARY KEY, digest TEXT NOT NULL)")
            self.db.commit()
        self._load_samples()

    def _load_samples(self) -> None:
        if not SAMPLES_DIR.exists():
            return
        for p in sorted(SAMPLES_DIR.glob("*.json")):
            try:
                run = json.loads(p.read_text())
            except json.JSONDecodeError:
                continue
            run["is_sample"] = True
            self.runs[run["id"]] = run

    def get(self, run_id: str) -> dict[str, Any] | None:
        run = self.runs.get(run_id)
        if run is None and self.db is not None:
            row = self.db.execute("SELECT json FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row:
                run = json.loads(row[0])
                self.runs[run_id] = run
                self._evict()
        return run

    def add(self, run: dict[str, Any]) -> None:
        self.runs[run["id"]] = run
        self._evict()
        self.touch(run)
        self.persist(run)

    def _evict(self) -> None:
        live = [r for r in self.runs.values() if not r.get("is_sample")]
        if len(live) > self.max_runs:
            for r in sorted(live, key=lambda r: r["created_at"])[: len(live) - self.max_runs]:
                self.runs.pop(r["id"], None)
                self.versions.pop(r["id"], None)
                self.events.pop(r["id"], None)

    def touch(self, run: dict[str, Any]) -> None:
        rid = run["id"]
        run["updated_at"] = round(time.time(), 3)
        self.versions[rid] += 1
        ev = self.events.get(rid)
        if ev is not None:
            ev.set()

    def persist(self, run: dict[str, Any]) -> None:
        if self.db is not None and not run.get("is_sample"):
            self.db.execute("INSERT OR REPLACE INTO runs (id, created_at, json) VALUES (?, ?, ?)",
                            (run["id"], run["created_at"], json.dumps(run)))
            self.db.commit()

    # ---- capability tokens: whoever holds the token returned at creation may answer / re-fork the run
    def set_token(self, run_id: str, token: str) -> None:
        d = _digest(token)
        self.tokens[run_id] = d
        if len(self.tokens) > 5000:
            for k in list(self.tokens)[:1000]:
                self.tokens.pop(k, None)
        if self.db is not None:
            self.db.execute("INSERT OR REPLACE INTO tokens (run_id, digest) VALUES (?, ?)", (run_id, d))
            self.db.commit()

    def check_token(self, run_id: str, token: str | None) -> bool:
        d = self.tokens.get(run_id)
        if d is None and self.db is not None:
            row = self.db.execute("SELECT digest FROM tokens WHERE run_id = ?", (run_id,)).fetchone()
            d = row[0] if row else None
        return bool(d and token and hmac.compare_digest(d, _digest(token)))

    def event(self, run_id: str) -> asyncio.Event:
        if run_id not in self.events:
            self.events[run_id] = asyncio.Event()
        return self.events[run_id]

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        return sorted(self.runs.values(), key=lambda r: (not r.get("is_sample"), r["created_at"]), reverse=True)[:limit]


class RateLimiter:
    """Sliding-window per-client limit plus a global daily spend cap (USD, from metered token usage)."""

    def __init__(self, per_window: int = 6, window_s: float = 600.0, daily_budget_usd: float = 5.0) -> None:
        self.per_window = per_window
        self.window_s = window_s
        self.daily_budget_usd = daily_budget_usd
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.day = time.strftime("%Y-%m-%d", time.gmtime())
        self.spent = 0.0

    def _roll(self) -> None:
        d = time.strftime("%Y-%m-%d", time.gmtime())
        if d != self.day:
            self.day, self.spent = d, 0.0

    def check(self, client: str) -> str | None:
        self._roll()
        if self.spent >= self.daily_budget_usd:
            return "The public demo's daily inference budget is used up. Sample runs remain available; please try again tomorrow."
        if len(self.hits) > 5000:  # bound memory: forget idle clients
            for k in [k for k, v in self.hits.items() if not v][:2500]:
                self.hits.pop(k, None)
        q = self.hits[client]
        t = time.monotonic()
        while q and t - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.per_window:
            return f"Rate limit: at most {self.per_window} live runs per {int(self.window_s // 60)} minutes per visitor."
        q.append(t)
        return None

    def budget_message(self) -> str | None:
        self._roll()
        if self.spent >= self.daily_budget_usd:
            return "The public demo's daily inference budget is used up. Sample runs remain available; please try again tomorrow."
        return None

    def add_spend(self, usd: float) -> None:
        self._roll()
        self.spent += usd
