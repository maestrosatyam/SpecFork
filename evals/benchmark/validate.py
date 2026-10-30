"""Validate the SpecFork benchmark (specs.json).

Checks, per item:
  * schema: required fields, unique ids, signature/test-input agreement, 10-20 test inputs,
    everything JSON-serialisable;
  * the reference compiles in a fresh namespace, defines the signature's function, runs on
    every test input within a per-call time limit, and returns JSON-serialisable values
    (an exception is allowed and recorded as its type, e.g. "ValueError");
  * ambiguous items have >= 1 axis; every axis has >= 2 interpretations, an `intended`
    interpretation, and >= 1 alt_reference; every alt_reference names a non-intended
    interpretation, runs cleanly, and DIFFERS from the reference on >= 1 test input
    (i.e. the test inputs distinguish the interpretations);
  * control items have no axes.

Outcomes are compared after normalisation: numbers -> float rounded to 9 decimals
(so 2 == 2.0), tuples -> lists, exceptions -> "!<ExceptionType>".

Usage:  python evals/benchmark/validate.py [path/to/specs.json] [-v]
Exit code 0 if everything passes, 1 otherwise.
"""

from __future__ import annotations

import copy
import json
import math
import signal
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CALL_TIMEOUT_S = 2.0
REQUIRED = ["id", "category", "ambiguous", "spec", "signature", "axes", "intent", "reference", "test_inputs"]


class CallTimeout(Exception):
    pass


def _alarm(signum, frame):  # pragma: no cover - only fires on runaway code
    raise CallTimeout()


def load_function(src: str, name: str):
    ns: dict = {"__name__": f"bench_{name}"}
    exec(compile(src, f"<{name}>", "exec"), ns)  # noqa: S102 - trusted, hand-written benchmark references
    fn = ns.get(name)
    if not callable(fn):
        raise AssertionError(f"code does not define function {name!r}")
    return fn


def normalize(v):
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return repr(f)
        return round(f, 9) + 0.0  # +0.0 folds -0.0 into 0.0
    if isinstance(v, (list, tuple)):
        return [normalize(x) for x in v]
    if isinstance(v, dict):
        return {str(k): normalize(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    return repr(v)


def run(fn, args: dict) -> tuple[str, object, float]:
    """Returns (kind, value, seconds); kind is 'ok' or 'error' (value = exception type name)."""
    signal.setitimer(signal.ITIMER_REAL, CALL_TIMEOUT_S)
    t0 = time.perf_counter()
    try:
        val = fn(**copy.deepcopy(args))
        kind = "ok"
    except CallTimeout:
        val, kind = "Timeout", "error"
    except Exception as e:  # noqa: BLE001 - recording any error is the point
        val, kind = type(e).__name__, "error"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return kind, val, time.perf_counter() - t0


def outcome_key(kind: str, val) -> str:
    if kind == "error":
        return f"!{val}"
    return json.dumps(normalize(val), sort_keys=True, ensure_ascii=False)


def validate_item(item: dict, problems: list[str]) -> dict:
    iid = item.get("id", "<no id>")

    def bad(msg: str) -> None:
        problems.append(f"[{iid}] {msg}")

    for f in REQUIRED:
        if f not in item:
            bad(f"missing field {f!r}")
    if any(f not in item for f in ("signature", "reference", "test_inputs")):
        return {"id": iid}

    sig = item["signature"]
    name = sig.get("name")
    param_names = [p["name"] for p in sig.get("params", [])]
    if not sig.get("returns"):
        bad("signature.returns missing")
    for p in sig.get("params", []):
        if not {"name", "type", "description"} <= set(p):
            bad(f"param {p} missing name/type/description")

    inputs = item["test_inputs"]
    if not 10 <= len(inputs) <= 20:
        bad(f"{len(inputs)} test inputs (want 10-20)")
    seen_inputs = set()
    for i, args in enumerate(inputs):
        if sorted(args) != sorted(param_names):
            bad(f"test_inputs[{i}] keys {sorted(args)} != params {sorted(param_names)}")
        k = json.dumps(args, sort_keys=True)
        if k in seen_inputs:
            bad(f"duplicate test input {k}")
        seen_inputs.add(k)

    # Reference
    try:
        ref = load_function(item["reference"], name)
    except Exception as e:  # noqa: BLE001
        bad(f"reference failed to load: {type(e).__name__}: {e}")
        return {"id": iid}
    ref_out, n_err, slowest = [], 0, 0.0
    for i, args in enumerate(inputs):
        kind, val, dt = run(ref, args)
        slowest = max(slowest, dt)
        if kind == "error":
            n_err += 1
            if val == "Timeout":
                bad(f"reference timed out on test_inputs[{i}]")
        else:
            try:
                json.dumps(val)
            except TypeError:
                bad(f"reference output on test_inputs[{i}] is not JSON-serialisable: {val!r}")
        ref_out.append(outcome_key(kind, val))
    if n_err == len(inputs):
        bad("reference raises on every test input")
    if slowest > 0.5:
        bad(f"reference too slow ({slowest:.2f}s on one input)")
    # Determinism: run once more and compare.
    if [outcome_key(*run(ref, a)[:2]) for a in inputs] != ref_out:
        bad("reference is not deterministic")

    # Axes
    axes = item.get("axes", [])
    n_alts = 0
    min_distinguishing = None
    if item.get("ambiguous"):
        if not axes:
            bad("ambiguous item has no axes")
    elif axes:
        bad("control item should have no axes")
    axis_ids = set()
    for ax in axes:
        aid = ax.get("id", "?")
        if aid in axis_ids:
            bad(f"duplicate axis id {aid}")
        axis_ids.add(aid)
        interps = ax.get("interpretations", [])
        if len(interps) < 2:
            bad(f"axis {aid}: needs >= 2 interpretations")
        if ax.get("intended") not in interps:
            bad(f"axis {aid}: 'intended' is not one of its interpretations")
        alts = ax.get("alt_references", [])
        if not alts:
            bad(f"axis {aid}: no alt_references")
        covered = set()
        for j, alt in enumerate(alts):
            alt_code = alt["code"] if isinstance(alt, dict) else alt
            interp = alt.get("interpretation") if isinstance(alt, dict) else None
            if interp is not None:
                if interp not in interps:
                    bad(f"axis {aid} alt {j}: interpretation not listed in axis.interpretations")
                if interp == ax.get("intended"):
                    bad(f"axis {aid} alt {j}: alt implements the intended interpretation")
                covered.add(interp)
            try:
                fn = load_function(alt_code, name)
            except Exception as e:  # noqa: BLE001
                bad(f"axis {aid} alt {j}: failed to load: {type(e).__name__}: {e}")
                continue
            n_alts += 1
            diffs = 0
            for i, args in enumerate(inputs):
                kind, val, _ = run(fn, args)
                if val == "Timeout" and kind == "error":
                    bad(f"axis {aid} alt {j}: timed out on test_inputs[{i}]")
                if outcome_key(kind, val) != ref_out[i]:
                    diffs += 1
            if diffs == 0:
                bad(f"axis {aid} alt {j} ({interp}): identical to reference on every test input")
            min_distinguishing = diffs if min_distinguishing is None else min(min_distinguishing, diffs)
        missing = [x for x in interps if x != ax.get("intended") and x not in covered]
        if missing and all(isinstance(a, dict) for a in alts):
            bad(f"axis {aid}: no alt_reference for interpretation(s) {missing}")

    for f in ("spec", "intent"):
        if not str(item.get(f, "")).strip():
            bad(f"empty {f}")
    try:
        json.dumps(item)
    except TypeError as e:
        bad(f"item not JSON-serialisable: {e}")

    return {
        "id": iid,
        "category": item.get("category", ""),
        "ambiguous": bool(item.get("ambiguous")),
        "axes": len(axes),
        "alts": n_alts,
        "inputs": len(inputs),
        "ref_errors": n_err,
        "min_diff": min_distinguishing,
        "distinct_ref_outputs": len(set(ref_out)),
        "slowest_ms": slowest * 1000,
    }


def main(argv: list[str]) -> int:
    verbose = "-v" in argv
    paths = [a for a in argv if not a.startswith("-")]
    path = Path(paths[0]) if paths else HERE / "specs.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    signal.signal(signal.SIGALRM, _alarm)

    problems: list[str] = []
    ids = [it.get("id") for it in items]
    for dup in {i for i in ids if ids.count(i) > 1}:
        problems.append(f"duplicate id {dup!r}")

    rows = [validate_item(it, problems) for it in items]

    hdr = f"{'id':<20} {'category':<14} {'amb':<4} {'axes':>4} {'alts':>4} {'inputs':>6} {'ref_err':>7} {'min_diff':>8} {'distinct':>8} {'max_ms':>7}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if "inputs" not in r:
            print(f"{r['id']:<20} (failed to load)")
            continue
        md = "-" if r["min_diff"] is None else str(r["min_diff"])
        print(f"{r['id']:<20} {r['category']:<14} {'Y' if r['ambiguous'] else 'n':<4} {r['axes']:>4} {r['alts']:>4} "
              f"{r['inputs']:>6} {r['ref_errors']:>7} {md:>8} {r['distinct_ref_outputs']:>8} {r['slowest_ms']:>7.2f}")
    print("-" * len(hdr))
    ok_rows = [r for r in rows if "inputs" in r]
    n_amb = sum(r["ambiguous"] for r in ok_rows)
    print(f"items: {len(items)}  ambiguous: {n_amb}  controls: {len(ok_rows) - n_amb}  "
          f"axes: {sum(r['axes'] for r in ok_rows)}  alt_references: {sum(r['alts'] for r in ok_rows)}  "
          f"test_inputs: {sum(r['inputs'] for r in ok_rows)}")
    print("columns: min_diff = fewest test inputs on which any alt_reference disagrees with the reference; "
          "distinct = distinct reference outcomes across the item's inputs")

    if verbose:
        for it in items:
            print(f"\n== {it['id']}")
            fn = load_function(it["reference"], it["signature"]["name"])
            for args in it["test_inputs"]:
                kind, val, _ = run(fn, args)
                shown = repr(val) if kind == "ok" else f"raises {val}"
                print(f"  {json.dumps(args, ensure_ascii=False)} -> {shown}")

    if problems:
        print(f"\nFAIL: {len(problems)} problem(s)")
        for p in problems:
            print("  - " + p)
        return 1
    print("\nPASS: all checks succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
