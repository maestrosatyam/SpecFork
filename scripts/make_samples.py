#!/usr/bin/env python3
"""Record real SpecFork runs for the preset specs (live Nebius inference) and store them as
sample runs in app/samples/ (shown in the UI with a "recorded run" banner).

Usage: .venv/bin/python scripts/make_samples.py [--base http://localhost:8000] [--presets split_bill,...] [--n 24]
Answers: for each ambiguity question the script picks the option listed in ANSWER_HINTS (substring match on the
option label) or, failing that, the most common behaviour. Every recorded run is a real run.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.cluster import compatible_option_ids  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ANSWER_HINTS = {"split_bill": ["first", "add up", "sum", "raise", "error"], "business_days": ["swap", "inclusive", "exclud"],
                "dedupe_emails": ["first", "original"], "round_grade": ["90"], "truncate": ["includ", "total"],
                "percent_change": ["none", "error", "undefined"]}


def wait(c: httpx.Client, rid: str, statuses: set[str], timeout: float = 600) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = c.get(f"/api/runs/{rid}").json()
        if r["status"] in statuses:
            return r
        time.sleep(1.5)
    raise TimeoutError(rid)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--presets", default="")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--converge", type=int, default=24)
    a = ap.parse_args()
    c = httpx.Client(base_url=a.base, timeout=60)
    presets = c.get("/api/presets").json()
    if a.presets:
        presets = [p for p in presets if p["id"] in a.presets.split(",")]
    out = ROOT / "app" / "samples"
    out.mkdir(exist_ok=True)
    for p in presets:
        print(f"== {p['id']}", flush=True)
        rid = c.post("/api/runs", json={"spec": p["spec"], "n_samples": a.n, "preset_id": p["id"]}).json()["id"]
        run = wait(c, rid, {"awaiting_answers", "error"})
        if run["status"] == "error":
            print("  error:", run.get("error"))
            continue
        answers = {q["id"]: q["answer_option_id"] for q in run["questions"]
                   if q["kind"] == "likely_bug" and q.get("answer_option_id")}
        for q in run["questions"]:
            if q["kind"] not in ("ambiguity", "assumption"):
                continue
            ok = set(compatible_option_ids(run["questions"], answers, q["id"], run["clusters"]))
            cands = [o for o in q["options"] if o["id"] in ok] or q["options"]
            hints = ANSWER_HINTS.get(p["id"], [])
            if q["kind"] == "assumption":  # recorded samples keep what the implementations assumed
                pick = next((o for o in cands if not o.get("is_alternative")), cands[0])
            else:
                pick = next((o for h in hints for o in cands if h in o["label"].lower()), cands[0])
            answers[q["id"]] = pick["id"]
            print(f"  Q: {q['text']}\n     -> {pick['label']}")
        c.post(f"/api/runs/{rid}/answers", json={"answers": answers})
        run = wait(c, rid, {"resolved"})
        if a.converge:
            c.post(f"/api/runs/{rid}/converge", json={"n_samples": a.converge})
            time.sleep(2)
            run = wait(c, rid, {"resolved"})
        res = run["resolution"]
        conv = res.get("convergence") or {}
        print(f"  behaviours={len([x for x in run['clusters'] if x['kind'] == 'behavior'])} "
              f"before={res['agreement_before']:.0%} after={conv.get('agreement_after', 0):.0%} "
              f"cost=${run['metrics']['total_cost_usd']:.4f} calls={run['metrics']['n_calls']}")
        run["is_sample"] = True
        (out / f"{p['id']}.json").write_text(json.dumps(run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
