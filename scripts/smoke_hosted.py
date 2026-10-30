#!/usr/bin/env python3
"""Unauthenticated smoke test of the public SpecFork deployment (what a judge does).

Usage: .venv/bin/python scripts/smoke_hosted.py https://<host> [--live]
Writes evidence/HOSTED_SMOKE_TEST.md. --live also performs one real fork (uses Nebius inference).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    base = sys.argv[1].rstrip("/")
    live = "--live" in sys.argv
    c = httpx.Client(base_url=base, timeout=60, follow_redirects=True)  # no cookies, no auth
    rows: list[tuple[str, bool, str]] = []

    def check(name: str, fn) -> None:
        t0 = time.perf_counter()
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        rows.append((name, ok, f"{detail} ({time.perf_counter() - t0:.2f}s)"))
        print(("PASS " if ok else "FAIL ") + name + " - " + detail, flush=True)

    def index():
        r = c.get("/")
        return r.status_code == 200 and "<div id=\"root\"" in r.text, f"HTTP {r.status_code}, {len(r.text)} bytes"

    def health():
        r = c.get("/api/health")
        j = r.json()
        return r.status_code == 200 and j.get("llm_configured") is True, json.dumps(j)

    def presets():
        p = c.get("/api/presets").json()
        return len(p) >= 5 and any(x.get("sample_run_id") for x in p), f"{len(p)} presets, {sum(1 for x in p if x.get('sample_run_id'))} with sample runs"

    def sample():
        p = c.get("/api/presets").json()
        rid = next(x["sample_run_id"] for x in p if x.get("sample_run_id"))
        r = c.get(f"/api/runs/{rid}").json()
        models = sorted({t["model"] for t in r["trace"]})
        return r["status"] == "resolved" and models, f"run {rid}: {len(r['trace'])} Nebius calls, models {models}"

    def sse():
        p = c.get("/api/presets").json()
        rid = next(x["sample_run_id"] for x in p if x.get("sample_run_id"))
        with c.stream("GET", f"/api/runs/{rid}/events") as s:
            text = ""
            for chunk in s.iter_text():
                text += chunk
                if "event: end" in text:
                    break
        return "event: snapshot" in text and "event: end" in text, "snapshot + end received"

    def tests_file():
        p = c.get("/api/presets").json()
        rid = next(x["sample_run_id"] for x in p if x.get("sample_run_id"))
        r = c.get(f"/api/runs/{rid}/tests.py")
        return r.status_code == 200 and "def test_" in r.text, f"HTTP {r.status_code}"

    def live_run():
        r = c.post("/api/runs", json={"spec": "Return the number of vowels in a word.", "n_samples": 8})
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        rid = r.json()["id"]
        for _ in range(150):
            run = c.get(f"/api/runs/{rid}").json()
            if run["status"] in ("awaiting_answers", "error"):
                break
            time.sleep(2)
        return run["status"] == "awaiting_answers", (f"run {rid}: {run['status']}, {run['metrics']['n_calls']} calls, "
                                                      f"${run['metrics']['total_cost_usd']:.4f}, {run['metrics']['wall_time_s']}s")

    check("GET / serves the app", index)
    check("GET /api/health reports Nebius configured", health)
    check("GET /api/presets", presets)
    check("recorded sample run with Nebius trace", sample)
    check("SSE event stream", sse)
    check("tests.py download", tests_file)
    if live:
        check("live fork (real Nebius inference)", live_run)

    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    md = [f"# Hosted smoke test\n", f"Target: {base}  \nRun at: {stamp}  \nClient: unauthenticated `httpx` from a fresh process (no cookies).\n",
          "| Check | Result | Detail |", "|---|---|---|"]
    md += [f"| {n} | {'PASS' if ok else 'FAIL'} | {d.replace('|', '/')} |" for n, ok, d in rows]
    (ROOT / "evidence" / "HOSTED_SMOKE_TEST.md").write_text("\n".join(md) + "\n")
    return 0 if all(ok for _, ok, _ in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
