"""In-memory run store with JSON persistence, change notification and abuse controls."""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

SAMPLES_DIR = Path(__file__).with_name("samples")


class RunStore:
    def __init__(self, data_dir: str | os.PathLike[str] | None = None, max_runs: int = 300) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, int] = defaultdict(int)
        self.events: dict[str, asyncio.Event] = {}
        self.max_runs = max_runs
        self.data_dir = Path(data_dir) if data_dir else None
        if self.data_dir:
            self.data_dir.mkdir(parents=True, exist_ok=True)
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
        if run is None and self.data_dir:
            p = self.data_dir / f"{run_id}.json"
            if p.exists() and p.parent == self.data_dir:
                run = json.loads(p.read_text())
                self.runs[run_id] = run
        return run

    def add(self, run: dict[str, Any]) -> None:
        self.runs[run["id"]] = run
        live = [r for r in self.runs.values() if not r.get("is_sample")]
        if len(live) > self.max_runs:
            for r in sorted(live, key=lambda r: r["created_at"])[: len(live) - self.max_runs]:
                self.runs.pop(r["id"], None)
                self.versions.pop(r["id"], None)
                self.events.pop(r["id"], None)
        self.touch(run)

    def touch(self, run: dict[str, Any]) -> None:
        rid = run["id"]
        run["updated_at"] = round(time.time(), 3)
        self.versions[rid] += 1
        ev = self.events.get(rid)
        if ev is not None:
            ev.set()

    def persist(self, run: dict[str, Any]) -> None:
        if self.data_dir and not run.get("is_sample"):
            tmp = self.data_dir / f"{run['id']}.json.tmp"
            tmp.write_text(json.dumps(run))
            tmp.replace(self.data_dir / f"{run['id']}.json")

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
