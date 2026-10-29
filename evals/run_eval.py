#!/usr/bin/env python3
"""Live evaluation of SpecFork against baselines on the hand-written ambiguity benchmark.

Conditions (same fast model, same N, same fixed signature for every condition):
  B0  no clarification: N implementations straight from the original spec
  B1  ask-first baseline: one Nemotron call lists clarifying questions (no execution); a simulated
      product owner answers them from the hidden intent; the deep model rewrites the spec; N implementations
  SF  SpecFork: fan-out → execute → cluster → witness questions; the simulated owner picks options;
      clarified spec; N fresh implementations (the "re-fork")

Primary metric: intent alignment = share of executed implementations that match the hidden reference
implementation on ALL hidden test inputs (never shown to any model). Also reported: questions asked,
false alarms on unambiguous control specs, cost, tokens, latency.

Usage: .venv/bin/python evals/run_eval.py [--n 12] [--items id1,id2] [--concurrency 3]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import prompts  # noqa: E402
from app.cluster import outcome_key  # noqa: E402
from app.llm import MODEL_DEEP, MODEL_FAST, NebiusClient, extract_json  # noqa: E402
from app.main import _load_dotenv  # noqa: E402,F401  (loads .env)
from app.pipeline import SpecFork, add_trace, extract_code, new_run  # noqa: E402
from app.sandbox import check_code, exec_semaphore, run_function  # noqa: E402

SIM_USER_SYSTEM = """You are the product owner who wrote a function spec. Your full, private intent is below.
Answer the clarifying question by choosing the option that matches your intent. If none matches exactly,
choose the closest. Reply with JSON only: {"option": "<option id>"}"""

SIM_USER_FREE_SYSTEM = """You are the product owner who wrote a function spec. Your full, private intent is below.
Answer each clarifying question briefly and precisely according to your intent (one or two sentences each).
If a question is irrelevant to your intent, say "No preference." Reply with JSON only:
{"answers": [{"question": str, "answer": str}]}"""

ASK_SYSTEM = """You are a careful software engineer about to implement the function spec below.
Before writing code, list the clarifying questions you would ask the product owner, most important first
(at most 5). Only ask questions whose answers would change the function's behaviour.
If the spec is already unambiguous, return an empty list. Reply with JSON only: {"questions": [str]}"""


async def implement_many(eng: SpecFork, run: dict[str, Any], spec: str, sig: dict[str, Any], n: int, purpose: str,
                         seed_base: int) -> list[dict[str, Any]]:
    impls = [{"id": f"{purpose}{k}", "index": k, "model": MODEL_FAST, "status": "pending"} for k in range(n)]
    await asyncio.gather(*(eng._one_impl(run, i, spec, run["hidden_inputs"], seed_base + i["index"], purpose) for i in impls))
    return impls


def alignment(impls: list[dict[str, Any]], expected: dict[str, str]) -> tuple[int, int]:
    ok = n = 0
    for i in impls:
        if i["status"] != "executed":
            continue
        n += 1
        if all(outcome_key(i["outcomes"].get(k)) == v for k, v in expected.items()):
            ok += 1
    return ok, n


async def reference_outcomes(item: dict[str, Any], inputs: list[dict[str, Any]]) -> dict[str, str]:
    async with exec_semaphore():
        res = await run_function(item["reference"], item["signature"]["name"], inputs, per_call_timeout_s=2.0)
    assert res.ok, res.error
    return {k: outcome_key(v) for k, v in res.outcomes.items()}


async def eval_item(item: dict[str, Any], client: NebiusClient, n: int, sem: asyncio.Semaphore) -> dict[str, Any]:
    async with sem:
        t0 = time.perf_counter()
        sig = {**item["signature"], "docstring": ""}
        hidden = [{"id": f"h{k}", "args": a} for k, a in enumerate(item["test_inputs"])]
        expected = await reference_outcomes(item, hidden)
        out: dict[str, Any] = {"id": item["id"], "ambiguous": item["ambiguous"], "n_axes": len(item["axes"]), "conditions": {}}
        seed = sum(map(ord, item["id"])) * 1000

        # ---------------- B0
        r0 = new_run(f"b0-{item['id']}", item["spec"], n)
        r0["signature"], r0["hidden_inputs"] = sig, hidden
        eng = SpecFork(client, lambda r: None)
        impls = await implement_many(eng, r0, item["spec"], sig, n, "b0_", seed)
        ok, k = alignment(impls, expected)
        out["conditions"]["B0"] = {"aligned": ok, "executed": k, "alignment": ok / k if k else 0.0, "questions": 0,
                                   "cost_usd": r0["metrics"]["total_cost_usd"], "calls": r0["metrics"]["n_calls"]}

        # ---------------- B1
        r1 = new_run(f"b1-{item['id']}", item["spec"], n)
        r1["signature"], r1["hidden_inputs"] = sig, hidden
        try:
            raw = await eng._json_call(r1, "ask", ASK_SYSTEM, prompts.frame_user(item["spec"], sig),
                                       model=MODEL_FAST, thinking=True, max_tokens=6000, temperature=0.4)
            qs = [str(q) for q in (raw.get("questions") or [])][:5]
            spec1 = item["spec"]
            if qs:
                ans = await eng._json_call(r1, "sim_user", SIM_USER_FREE_SYSTEM,
                                           f"Spec:\n{item['spec']}\n\nYour intent:\n{item['intent']}\n\nQuestions:\n{json.dumps(qs, indent=1)}",
                                           model=MODEL_FAST, thinking=False, max_tokens=1500, temperature=0.0)
                decisions = [{"question": a.get("question", ""), "answer": a.get("answer", "")} for a in ans.get("answers") or []]
                cl = await eng._json_call(r1, "clarify", prompts.CLARIFY_SYSTEM, prompts.clarify_user(item["spec"], decisions),
                                          model=MODEL_DEEP, thinking=False, max_tokens=1500, temperature=0.3)
                spec1 = str(cl.get("clarified_spec") or item["spec"])
            impls = await implement_many(eng, r1, spec1, sig, n, "b1_", seed + 100)
            ok, k = alignment(impls, expected)
            out["conditions"]["B1"] = {"aligned": ok, "executed": k, "alignment": ok / k if k else 0.0, "questions": len(qs),
                                       "question_texts": qs, "clarified_spec": spec1,
                                       "cost_usd": r1["metrics"]["total_cost_usd"], "calls": r1["metrics"]["n_calls"]}
        except Exception as e:  # noqa: BLE001
            out["conditions"]["B1"] = {"error": f"{type(e).__name__}: {str(e)[:200]}", "cost_usd": r1["metrics"]["total_cost_usd"]}

        # ---------------- SpecFork
        rs = new_run(f"sf-{item['id']}", item["spec"], n)
        rs["signature"] = sig
        try:
            await eng.run_all(rs)
            if rs["status"] != "awaiting_answers":
                raise RuntimeError(rs.get("error"))
            inputs = {i["id"]: i for i in rs["inputs"]}
            answers = {}
            for q in rs["questions"]:
                if q["kind"] != "ambiguity":
                    continue
                opts = [{"id": o["id"], "answer": o["label"],
                         "examples": [f"{sig['name']}(**{json.dumps(inputs[e['input_id']]['args'])}) -> {e['value_repr']}" for e in o["examples"]]}
                        for o in q["options"]]
                pick = await eng._json_call(rs, "sim_user", SIM_USER_SYSTEM,
                                            f"Spec:\n{item['spec']}\n\nYour intent:\n{item['intent']}\n\nQuestion: {q['text']}\nOptions:\n{json.dumps(opts, indent=1)}",
                                            model=MODEL_FAST, thinking=False, max_tokens=300, temperature=0.0)
                oid = pick.get("option")
                answers[q["id"]] = oid if any(o["id"] == oid for o in q["options"]) else q["options"][0]["id"]
            await eng.resolve(rs, answers)
            res = rs["resolution"]
            rs["hidden_inputs"] = hidden
            impls = await implement_many(eng, rs, res["clarified_spec"], sig, n, "sf_", seed + 200)
            ok, k = alignment(impls, expected)
            # did the chosen behaviour itself match the hidden reference?
            chosen = next(i for i in rs["implementations"] if i["id"] == res["chosen_impl_id"])
            async with exec_semaphore():
                chk = await run_function(chosen["code"], sig["name"], hidden)
            chosen_ok = chk.ok and all(outcome_key(chk.outcomes.get(k2)) == v for k2, v in expected.items())
            # original fan-out alignment with the hidden reference (a second B0-style sample, for free)
            orig_ok = 0
            orig_n = 0
            for i in rs["implementations"]:
                if i["status"] == "executed" and i.get("code"):
                    orig_n += 1
            out["conditions"]["SF"] = {
                "aligned": ok, "executed": k, "alignment": ok / k if k else 0.0,
                "questions": sum(1 for q in rs["questions"] if q["kind"] == "ambiguity"),
                "likely_bugs": sum(1 for q in rs["questions"] if q["kind"] == "likely_bug"),
                "question_texts": [q["text"] for q in rs["questions"] if q["kind"] == "ambiguity"],
                "behaviours": len([c for c in rs["clusters"] if c["kind"] == "behavior"]),
                "fanout_executed": orig_n, "chosen_matches_reference": chosen_ok,
                "agreement_before": res["agreement_before"], "clarified_spec": res["clarified_spec"],
                "cost_usd": rs["metrics"]["total_cost_usd"], "calls": rs["metrics"]["n_calls"],
                "rejected": sum(1 for i in rs["implementations"] if i["status"] == "rejected"),
            }
            _ = orig_ok
        except Exception as e:  # noqa: BLE001
            out["conditions"]["SF"] = {"error": f"{type(e).__name__}: {str(e)[:200]}", "cost_usd": rs["metrics"]["total_cost_usd"]}
        out["wall_s"] = round(time.perf_counter() - t0, 1)
        line = " ".join(f"{c}={v.get('aligned', '-')}/{v.get('executed', '-')}" for c, v in out["conditions"].items())
        print(f"[{item['id']:<20}] {line}  q(B1)={out['conditions']['B1'].get('questions')} q(SF)={out['conditions']['SF'].get('questions')} "
              f"{out['wall_s']}s", flush=True)
        return out


def summarize(results: list[dict[str, Any]], n: int) -> str:
    def agg(cond: str, amb: bool) -> dict[str, Any]:
        rows = [r["conditions"][cond] for r in results if r["ambiguous"] == amb and "alignment" in r["conditions"].get(cond, {})]
        if not rows:
            return {}
        return {
            "items": len(rows),
            "mean_alignment": statistics.mean(r["alignment"] for r in rows),
            "items_fully_aligned": sum(1 for r in rows if r["executed"] and r["aligned"] == r["executed"]),
            "items_majority_aligned": sum(1 for r in rows if r["executed"] and r["aligned"] / r["executed"] > 0.5),
            "mean_questions": statistics.mean(r["questions"] for r in rows),
            "cost_usd": sum(r["cost_usd"] for r in rows),
        }

    lines = [f"Implementations per condition per item: N={n}", "",
             "| Condition | Spec set | Items | Mean intent alignment | Items >50% aligned | Items 100% aligned | Mean questions | Cost (USD) |",
             "|---|---|---|---|---|---|---|---|"]
    for amb, label in ((True, "ambiguous"), (False, "control")):
        for cond, name in (("B0", "B0 no clarification"), ("B1", "B1 ask-first (no execution)"), ("SF", "SpecFork")):
            a = agg(cond, amb)
            if a:
                lines.append(f"| {name} | {label} | {a['items']} | {a['mean_alignment']:.1%} | {a['items_majority_aligned']} | "
                             f"{a['items_fully_aligned']} | {a['mean_questions']:.2f} | ${a['cost_usd']:.4f} |")
    errs = [(r["id"], c, v["error"]) for r in results for c, v in r["conditions"].items() if "error" in v]
    if errs:
        lines += ["", "Errors:", *[f"- {i} / {c}: {e}" for i, c, e in errs]]
    sf = [r["conditions"]["SF"] for r in results if r["ambiguous"] and "chosen_matches_reference" in r["conditions"].get("SF", {})]
    if sf:
        lines += ["", f"SpecFork chosen behaviour matched the hidden reference on all hidden inputs in "
                      f"{sum(1 for x in sf if x['chosen_matches_reference'])}/{len(sf)} ambiguous items."]
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--items", default="")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--out", default=str(ROOT / "evals" / "results"))
    args = ap.parse_args()
    if not os.environ.get("NEBIUS_API_KEY"):
        print("NEBIUS_API_KEY missing", file=sys.stderr)
        return 2
    items = json.loads((ROOT / "evals" / "benchmark" / "specs.json").read_text())
    if args.items:
        wanted = set(args.items.split(","))
        items = [i for i in items if i["id"] in wanted]
    client = NebiusClient(max_concurrency=12)
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.time()
    results = await asyncio.gather(*(eval_item(i, client, args.n, sem) for i in items))
    await client.aclose()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    meta = {"timestamp": stamp, "n": args.n, "fast_model": MODEL_FAST, "deep_model": MODEL_DEEP,
            "prompt_version": prompts.PROMPT_VERSION, "wall_s": round(time.time() - t0, 1), "items": len(items)}
    (outdir / f"eval-{stamp}.json").write_text(json.dumps({"meta": meta, "results": results}, indent=1))
    summary = summarize(results, args.n)
    (outdir / f"eval-{stamp}.md").write_text(f"# Eval {stamp}\n\n```\n{json.dumps(meta, indent=1)}\n```\n\n{summary}\n")
    print(summary)
    print(f"\nwrote {outdir}/eval-{stamp}.json")
    return 0


if __name__ == "__main__":
    _ = (add_trace, extract_code, check_code, extract_json)
    sys.exit(asyncio.run(main()))
