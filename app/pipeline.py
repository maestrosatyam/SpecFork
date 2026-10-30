"""SpecFork orchestration: frame → fan-out → execute → cluster → explain → resolve → converge.

Model roles (all NVIDIA open models served by Nebius Token Factory):
  * fast model (Nemotron 3.5 Lightning): framing, many independent implementations (cheap, high throughput)
  * deep model (Nemotron 3 Ultra, reasoning on): explaining disagreements, rewriting the spec
Everything that decides (clustering, witnesses, tests, agreement) is deterministic code.
"""
from __future__ import annotations

import asyncio
import os
import hashlib
import json
import random
import re
import time
from typing import Any, Callable

from . import prompts
from .canon import canon
from .cluster import agreement, cluster_impls, find_axes, outcome_key, surviving_clusters
from .llm import MODEL_DEEP, MODEL_FAST, CallRecord, LLMError, NebiusClient, extract_json
from .sandbox import check_code, exec_semaphore, run_function

IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")
MAX_INPUTS = 24
FRAME_THINKING = os.environ.get("FRAME_THINKING", "0") == "1"


class PipelineError(RuntimeError):
    pass


# ---------------------------------------------------------------- helpers

def now() -> float:
    return round(time.time(), 3)


def new_run(run_id: str, spec: str, n_samples: int, preset_id: str | None = None,
            fast_model: str = MODEL_FAST, deep_model: str = MODEL_DEEP) -> dict[str, Any]:
    t = now()
    return {
        "id": run_id, "created_at": t, "updated_at": t, "status": "running", "stage": "frame",
        "spec": spec, "preset_id": preset_id, "is_sample": False,
        "settings": {"n_samples": n_samples, "fast_model": fast_model, "deep_model": deep_model,
                     "prompt_version": prompts.PROMPT_VERSION},
        "inputs": [], "implementations": [], "clusters": [], "questions": [], "trace": [],
        "metrics": {"total_cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "n_calls": 0, "wall_time_s": 0.0},
        "log": [],
    }


def extract_code(text: str) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    if blocks:
        return max(blocks, key=len).strip()
    return text.strip()


def validate_signature(raw: dict[str, Any]) -> dict[str, Any]:
    name = str(raw.get("name", "")).strip()
    if not IDENT.match(name):
        raise PipelineError(f"bad function name from framer: {name!r}")
    params = []
    for p in raw.get("params") or []:
        pname = str(p.get("name", "")).strip()
        if not IDENT.match(pname):
            raise PipelineError(f"bad parameter name: {pname!r}")
        params.append({"name": pname, "type": str(p.get("type", "Any"))[:60],
                       "description": str(p.get("description", ""))[:300]})
    if not params or len(params) > 6:
        raise PipelineError("framer returned no parameters or too many")
    ret = raw.get("returns") or {}
    return {"name": name, "params": params,
            "returns": {"type": str(ret.get("type", "Any"))[:60], "description": str(ret.get("description", ""))[:300]},
            "docstring": ""}


def _json_ok(v: Any, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if v is None or isinstance(v, (bool, int, float, str)):
        return not (isinstance(v, str) and len(v) > 500)
    if isinstance(v, list):
        return len(v) <= 200 and all(_json_ok(x, depth + 1) for x in v)
    if isinstance(v, dict):
        return len(v) <= 50 and all(isinstance(k, str) and _json_ok(x, depth + 1) for k, x in v.items())
    return False


def validate_inputs(raw_inputs: list[Any], sig: dict[str, Any], source: str) -> list[dict[str, Any]]:
    names = {p["name"] for p in sig["params"]}
    out, seen = [], set()
    for item in raw_inputs or []:
        args = item.get("args") if isinstance(item, dict) else None
        if not isinstance(args, dict) or set(args) != names or not _json_ok(args):
            continue
        key = json.dumps(args, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append({"args": args, "source": source, "note": str(item.get("note", ""))[:160]})
    return out


_FUZZ = {
    "int": [0, 1, 2, 3, 7, 10, -1, 100],
    "float": [0.0, 1.0, 0.5, 2.5, 1.005, 2.675, 99.99, 100.0, -3.5],
    "bool": [True, False],
    "str": ["", "a", "Hello World", "  padded  ", "ÉCOLE café", "o'neil-smith", "A-b_c d", "x" * 30],
}


def fuzz_value(t: str, name: str, rng: random.Random) -> Any:
    t = t.replace(" ", "")
    m = re.match(r"^(?:Optional\[(.*)\]|(.*)\|None)$", t)
    if m:
        inner = m.group(1) or m.group(2)
        return None if rng.random() < 0.25 else fuzz_value(inner, name, rng)
    lm = re.match(r"^(?:list|List)\[(.*)\]$", t)
    if lm:
        k = rng.choice([0, 1, 2, 3, 4, 5])
        return [fuzz_value(lm.group(1), name, rng) for _ in range(k)]
    if t == "str" and any(w in name.lower() for w in ("date", "day", "start", "end")):
        return rng.choice(["2024-02-29", "2023-12-31", "2024-01-01", "2025-03-09", "2024-11-03", "2023-02-28"])
    if t in _FUZZ:
        return rng.choice(_FUZZ[t])
    raise ValueError(t)


def fuzz_inputs(sig: dict[str, Any], seed_text: str, k: int = 6) -> list[dict[str, Any]]:
    rng = random.Random(int(hashlib.sha256(seed_text.encode()).hexdigest()[:8], 16))
    out = []
    try:
        for _ in range(k):
            out.append({"args": {p["name"]: fuzz_value(p["type"], p["name"], rng) for p in sig["params"]}, "note": "type-driven fuzz"})
    except ValueError:
        return []
    return out


def humanize_label(label: str) -> str:
    """Turn identifier-like labels ("extra_to_first") into readable text ("Extra to first")."""
    label = label.strip()
    if re.fullmatch(r"[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)+", label):
        label = re.sub(r"[_-]+", " ", label)
        label = label[:1].upper() + label[1:]
    return label


def add_trace(run: dict[str, Any], rec: CallRecord, reasoning: str = "") -> None:
    d = rec.to_dict()
    if reasoning:
        d["reasoning_excerpt"] = reasoning[:600]
    run["trace"].append(d)
    m = run["metrics"]
    m["n_calls"] += 1
    m["prompt_tokens"] += rec.prompt_tokens
    m["completion_tokens"] += rec.completion_tokens
    m["total_cost_usd"] = round(m["total_cost_usd"] + rec.cost_usd, 7)


def render_tests(sig: dict[str, Any], cases: list[dict[str, Any]], spec: str) -> str:
    """Deterministic pytest file: compares canonical forms, so it is robust to 3 vs 3.0 and tuple vs list."""
    import inspect

    from . import canon as canon_mod

    canon_src = inspect.getsource(canon_mod.canon)
    fname = sig["name"]
    rows = []
    for c in cases:
        rows.append(f"    ({json.dumps(c['args'], ensure_ascii=False)!r}, {c['expected_repr']!r}),")
    spec_comment = "\n".join("# " + line for line in spec.strip().splitlines())
    return f'''"""Locked behaviour for `{fname}`, generated by SpecFork from executed witness inputs.

Each case was produced by running the implementation that matches the product owner's answers.
Expected values are canonical reprs ("raises" means any exception is expected).
"""
# Clarified spec:
{spec_comment}
import datetime as _dt
import decimal as _decimal
import fractions as _fractions
import json
import math as _math

import pytest

from solution import {fname}  # noqa: E402  (put your implementation in solution.py)

RAISES = "raises"


{canon_src}

CASES = [
{chr(10).join(rows)}
]


@pytest.mark.parametrize("args_json,expected", CASES)
def test_{fname}(args_json, expected):
    args = json.loads(args_json)
    if expected == RAISES:
        with pytest.raises(Exception):
            {fname}(**args)
    else:
        assert canon({fname}(**args)) == expected
'''


# ---------------------------------------------------------------- pipeline

class SpecFork:
    def __init__(self, client: NebiusClient, notify: Callable[[dict[str, Any]], None]) -> None:
        self.client = client
        self.notify = notify

    def _log(self, run: dict[str, Any], stage: str, msg: str) -> None:
        run["log"].append({"t": now(), "stage": stage, "msg": msg})
        run["updated_at"] = now()
        self.notify(run)

    async def _chat(self, run: dict[str, Any], purpose: str, messages: list[dict[str, Any]], **kw: Any):
        trace: list[CallRecord] = []
        try:
            res = await self.client.chat(messages, purpose=purpose, trace=trace, **kw)
        finally:
            for rec in trace:
                add_trace(run, rec)
        if res.reasoning:
            run["trace"][-1]["reasoning_excerpt"] = res.reasoning[:600]
        return res

    async def _json_call(self, run, purpose, system, user, *, model, thinking, max_tokens, temperature=0.3, retries=1,
                         template_kwargs=None, fallback_no_thinking=False):
        last: Exception | None = None
        for attempt in range(retries + 1):
            think = thinking and not (fallback_no_thinking and attempt > 0)
            res = await self._chat(run, purpose, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                                   model=model, thinking=think, max_tokens=max_tokens, temperature=temperature,
                                   template_kwargs=template_kwargs if think else None)
            try:
                return extract_json(res.content)
            except ValueError as e:
                last = e
                self._log(run, run["stage"], f"{purpose}: unparseable JSON, retrying ({attempt + 1})")
        raise PipelineError(f"{purpose}: model did not return JSON ({last})")

    # ---- stage 1
    async def frame(self, run: dict[str, Any]) -> None:
        for attempt in range(2):
            try:
                return await self._frame_once(run)
            except PipelineError as e:
                if attempt == 1:
                    raise
                self._log(run, "frame", f"Framing output rejected ({e}); retrying")

    async def _frame_once(self, run: dict[str, Any]) -> None:
        run["stage"] = "frame"
        self._log(run, "frame", f"Framing the spec with {run['settings']['fast_model']}")
        fixed = run.get("signature")
        system = prompts.FRAME_INPUTS_SYSTEM if fixed else prompts.FRAME_SYSTEM
        raw = await self._json_call(run, "frame", system, prompts.frame_user(run["spec"], fixed),
                                    model=run["settings"]["fast_model"], thinking=FRAME_THINKING, max_tokens=8000, temperature=0.4,
                                    fallback_no_thinking=True)
        sig = validate_signature(fixed) if fixed else validate_signature(raw)
        model_inputs = validate_inputs(raw.get("inputs") or [], sig, "model")
        fz = validate_inputs(fuzz_inputs(sig, run["spec"]), sig, "fuzz")
        seen = {json.dumps(i["args"], sort_keys=True) for i in model_inputs}
        fz = [f for f in fz if json.dumps(f["args"], sort_keys=True) not in seen]
        allin = (model_inputs[: MAX_INPUTS - 4] + fz)[:MAX_INPUTS]
        if len(allin) < 4:
            raise PipelineError("could not build enough valid probe inputs")
        run["signature"] = sig
        run["inputs"] = [{"id": f"i{k}", **x} for k, x in enumerate(allin)]
        self._log(run, "frame", f"Signature {sig['name']}({', '.join(p['name'] for p in sig['params'])}); "
                                f"{len(model_inputs)} model probes + {len(fz)} fuzz probes")

    # ---- stage 2+3
    async def _one_impl(self, run: dict[str, Any], impl: dict[str, Any], spec: str, inputs: list[dict[str, Any]],
                        seed: int, purpose: str) -> None:
        sig = run["signature"]
        try:
            res = await self._chat(run, purpose, [{"role": "system", "content": prompts.IMPLEMENT_SYSTEM},
                                                  {"role": "user", "content": prompts.implement_user(spec, sig)}],
                                   model=impl["model"], thinking=False, max_tokens=1800, temperature=1.0, seed=seed)
        except LLMError as e:
            impl["status"], impl["reject_reason"] = "error", f"inference failed: {str(e)[:120]}"
            self.notify(run)
            return
        code = extract_code(res.content)
        impl["code"] = code
        chk = check_code(code, sig["name"])
        if not chk.ok:
            impl["status"], impl["reject_reason"] = "rejected", chk.reason
            self.notify(run)
            return
        impl["status"] = "generated"
        self.notify(run)
        async with exec_semaphore():
            ex = await run_function(code, sig["name"], [{"id": i["id"], "args": i["args"]} for i in inputs])
        if not ex.ok:
            impl["status"], impl["reject_reason"] = "error", f"execution failed: {ex.error}"
        else:
            impl["status"], impl["outcomes"] = "executed", ex.outcomes
        self.notify(run)

    async def fanout(self, run: dict[str, Any]) -> None:
        run["stage"] = "fanout"
        n = run["settings"]["n_samples"]
        run["implementations"] = [{"id": f"m{k}", "index": k, "model": run["settings"]["fast_model"], "status": "pending"}
                                  for k in range(n)]
        self._log(run, "fanout", f"Requesting {n} independent implementations from {run['settings']['fast_model']}")
        base = int(hashlib.sha256(run["spec"].encode()).hexdigest()[:6], 16)
        await asyncio.gather(*(self._one_impl(run, impl, run["spec"], run["inputs"], base + impl["index"], "implement")
                               for impl in run["implementations"]))
        run["stage"] = "execute"
        st = [i["status"] for i in run["implementations"]]
        self._log(run, "execute", f"Executed {st.count('executed')} implementations in the sandbox "
                                  f"({st.count('rejected')} rejected by the safety check, {st.count('error')} failed)")
        if st.count("executed") < 2:
            raise PipelineError("fewer than two implementations could be executed")

    # ---- stage 4
    def cluster(self, run: dict[str, Any]) -> list[Any]:
        run["stage"] = "cluster"
        ex = {i["id"]: i["outcomes"] for i in run["implementations"] if i["status"] == "executed"}
        ids = [i["id"] for i in run["inputs"]]
        cr = cluster_impls(ex, ids)
        for impl in run["implementations"]:
            if impl["id"] in cr.impl_cluster:
                impl["cluster_id"] = cr.impl_cluster[impl["id"]]
        run["clusters"] = cr.clusters
        rep = {c["id"]: ex[c["representative_impl_id"]] for c in cr.clusters}
        cost = {i["id"]: len(json.dumps(i["args"])) for i in run["inputs"]}
        axes = find_axes(cr.clusters, rep, ids, input_cost=cost)
        live = [c for c in cr.clusters if c["kind"] == "behavior"]
        self._log(run, "cluster", f"{len(ex)} implementations → {len(live)} distinct behaviours"
                                  f"{' + ' + str(len(cr.clusters) - len(live)) + ' crash cluster(s)' if len(cr.clusters) > len(live) else ''}; "
                                  f"{len(axes)} axes of disagreement")
        return axes

    # ---- stage 5
    async def explain(self, run: dict[str, Any], axes: list[Any]) -> None:
        run["stage"] = "explain"
        clusters = {c["id"]: c for c in run["clusters"]}
        impls = {i["id"]: i for i in run["implementations"]}
        inputs = {i["id"]: i for i in run["inputs"]}
        if not axes:
            run["questions"] = []
            self._log(run, "explain", "All implementations agree on every probe; looking for silent assumptions")
            await self.assumptions(run)
            return
        axes_payload, group_maps = [], []
        for k, ax in enumerate(axes):
            groups = {}
            gmap = {}
            for gi, part in enumerate(ax.partition):
                gid = f"g{gi}"
                gmap[gid] = list(part)
                groups[gid] = {
                    "clusters": [clusters[c]["label"] for c in part],
                    "implementations": sum(clusters[c]["size"] for c in part),
                    "outputs": {w: outcome_key(impls[clusters[part[0]]["representative_impl_id"]]["outcomes"][w])
                                for w in ax.witness_input_ids},
                }
            axes_payload.append({
                "axis_id": f"x{k}",
                "witness_inputs": {w: inputs[w]["args"] for w in ax.witness_input_ids},
                "groups": groups,
            })
            group_maps.append(gmap)
        clusters_payload = [{
            "label": c["label"], "implementations": c["size"], "kind": c["kind"],
            "code": (impls[c["representative_impl_id"]].get("code") or "")[:1400],
        } for c in run["clusters"][:8]]
        self._log(run, "explain", f"Asking {run['settings']['deep_model']} (reasoning on) to explain {len(axes)} disagreement(s)")
        try:
            raw = await self._json_call(run, "explain", prompts.EXPLAIN_SYSTEM,
                                        prompts.explain_user(run["spec"], run["signature"], axes_payload, clusters_payload),
                                        model=run["settings"]["deep_model"], thinking=True, max_tokens=16000, temperature=0.6,
                                        template_kwargs={"medium_effort": True}, fallback_no_thinking=True)
        except (LLMError, PipelineError) as e:
            self._log(run, "explain", f"Explainer unavailable ({str(e)[:80]}); using raw witness questions")
            raw = {"axes": []}
        by_label = {c["label"]: c for c in run["clusters"]}
        for lab, summ in (raw.get("cluster_summaries") or {}).items():
            if lab in by_label:
                by_label[lab]["summary"] = str(summ)[:160]
        expl = {a.get("axis_id"): a for a in raw.get("axes") or [] if isinstance(a, dict)}
        questions = []
        for k, (ax, gmap) in enumerate(zip(axes, group_maps)):
            e = expl.get(f"x{k}") or {}
            if e.get("merge_into") and any(q["id"] == f"q{e['merge_into'][1:]}" for q in questions):
                continue
            labels = {o.get("group"): humanize_label(str(o.get("label", "")))[:140]
                      for o in e.get("options") or [] if isinstance(o, dict)}
            options = []
            for gid, cids in gmap.items():
                options.append({
                    "id": f"q{k}{gid}", "label": labels.get(gid) or f"Behaviour {'/'.join(clusters[c]['label'] for c in cids)}",
                    "cluster_ids": cids,
                    "examples": [{"input_id": w, "value_repr": outcome_key(impls[clusters[cids[0]]["representative_impl_id"]]["outcomes"][w])}
                                 for w in ax.witness_input_ids],
                    "impl_count": sum(clusters[c]["size"] for c in cids),
                })
            options.sort(key=lambda o: -o["impl_count"])
            kind = "likely_bug" if e.get("kind") == "likely_bug" else "ambiguity"
            if kind == "likely_bug":
                n_exec = sum(c["size"] for c in run["clusters"]) or 1
                bug_mass = sum(o["impl_count"] for o in options if o["id"] in {f"q{k}{g}" for g in (e.get("bug_groups") or [])})
                if not e.get("bug_groups") or bug_mass / n_exec >= 0.25:
                    kind = "ambiguity"  # too many implementations do it to call it a bug
            q = {
                "id": f"q{k}", "kind": kind,
                "text": str(e.get("question") or f"What should {run['signature']['name']} return for "
                                                 f"{json.dumps(inputs[ax.witness_input_ids[0]]['args'])}?")[:300],
                "why": str(e.get("why") or "Independent implementations disagree on this input.")[:300],
                "witness_input_ids": ax.witness_input_ids, "options": options,
            }
            if kind == "likely_bug":
                bug = {f"q{k}{g}" for g in (e.get("bug_groups") or [])}
                good = [o for o in options if o["id"] not in bug] or options
                q["answer_option_id"] = good[0]["id"]
                for o in options:
                    o["is_bug"] = o["id"] in bug
            questions.append(q)
        run["questions"] = questions
        n_amb = sum(1 for q in questions if q["kind"] == "ambiguity")
        self._log(run, "explain", f"{n_amb} clarifying question(s), {len(questions) - n_amb} likely bug(s)")
        await self.assumptions(run)

    async def assumptions(self, run: dict[str, Any]) -> None:
        """Ask the deep model which consequential decisions every (or the majority) implementation made silently."""
        live = [c for c in run["clusters"] if c["kind"] == "behavior"]
        if not live:
            return
        impls = {i["id"]: i for i in run["implementations"]}
        major = live[0]
        rep = impls[major["representative_impl_id"]]
        outputs = [{"id": i["id"], "args": i["args"], "output": outcome_key(rep["outcomes"].get(i["id"]))[:160]}
                   for i in run["inputs"]]
        open_qs = [q["text"] for q in run["questions"]]
        n_total = sum(c["size"] for c in run["clusters"])
        self._log(run, "explain", f"Asking {run['settings']['deep_model']} for silent assumptions behind behaviour {major['label']}")
        try:
            raw = await self._json_call(run, "assumptions", prompts.ASSUME_SYSTEM,
                                        prompts.assume_user(run["spec"], run["signature"], rep.get("code") or "", outputs,
                                                            major["size"], n_total, open_qs),
                                        model=run["settings"]["deep_model"], thinking=True, max_tokens=12000, temperature=0.5,
                                        template_kwargs={"medium_effort": True}, fallback_no_thinking=True)
        except (LLMError, PipelineError) as e:
            self._log(run, "explain", f"Assumption review unavailable ({str(e)[:80]})")
            return
        valid_ids = {i["id"] for i in run["inputs"]}
        added = 0
        for k, a in enumerate((raw.get("assumptions") or [])[:3]):
            if not isinstance(a, dict) or not a.get("question") or not a.get("alternative_label"):
                continue
            affected = [i for i in (a.get("input_ids") or []) if isinstance(i, str) and i in valid_ids]
            # clusters that behave like the majority on the affected inputs keep the assumption
            keep_ids = [c["id"] for c in live
                        if all(outcome_key(impls[c["representative_impl_id"]]["outcomes"].get(i)) == outcome_key(rep["outcomes"].get(i))
                               for i in affected)]
            qid = f"a{k}"
            run["questions"].append({
                "id": qid, "kind": "assumption",
                "text": str(a["question"])[:300], "why": str(a.get("why") or "")[:300],
                "witness_input_ids": affected[:3], "affected_input_ids": affected,
                "agree_count": sum(c["size"] for c in live if c["id"] in keep_ids),
                "options": [
                    {"id": f"{qid}keep", "label": humanize_label(str(a.get("consensus_label") or "Keep the current behaviour"))[:140],
                     "cluster_ids": keep_ids, "impl_count": sum(c["size"] for c in live if c["id"] in keep_ids),
                     "examples": [{"input_id": i, "value_repr": outcome_key(rep["outcomes"].get(i))} for i in affected[:2]]},
                    {"id": f"{qid}alt", "label": humanize_label(str(a["alternative_label"]))[:140], "cluster_ids": [],
                     "impl_count": 0, "examples": [], "is_alternative": True,
                     "note": str(a.get("alternative_example") or "")[:200]},
                ],
            })
            added += 1
        self._log(run, "explain", f"{added} silent assumption(s) found")

    async def run_all(self, run: dict[str, Any]) -> None:
        t0 = time.perf_counter()
        try:
            await self.frame(run)
            await self.fanout(run)
            axes = self.cluster(run)
            await self.explain(run, axes)
            run["stage"] = "done"
            run["status"] = "awaiting_answers"
        except (PipelineError, LLMError) as e:
            run["status"], run["error"] = "error", str(e)[:400]
        except Exception as e:  # noqa: BLE001 - surface unexpected failures to the UI
            run["status"], run["error"] = "error", f"internal error: {type(e).__name__}: {str(e)[:200]}"
        finally:
            run["metrics"]["wall_time_s"] = round(run["metrics"]["wall_time_s"] + time.perf_counter() - t0, 2)
            self._log(run, run["stage"], "Ready for your answers" if run["status"] == "awaiting_answers" else f"Stopped: {run.get('error')}")

    # ---- resolve
    async def resolve(self, run: dict[str, Any], answers: dict[str, str]) -> None:
        t0 = time.perf_counter()
        try:
            qs = {q["id"]: q for q in run["questions"]}
            chosen_sets, decisions = [], []
            overrides: set[str] = set()
            for q in run["questions"]:
                oid = answers.get(q["id"]) or q.get("answer_option_id")
                opt = next((o for o in q["options"] if o["id"] == oid), None)
                if opt is None:
                    if q["kind"] in ("ambiguity", "assumption"):
                        raise PipelineError(f"question {q['id']} not answered")
                    continue
                q["answer_option_id"] = opt["id"]
                if opt.get("is_alternative"):
                    overrides.update(q.get("affected_input_ids") or [])
                    decisions.append({"question": q["text"], "answer": opt["label"], "example": opt.get("note", ""),
                                      "note": "Overrides what the implementations assumed."})
                    continue
                chosen_sets.append(set(opt["cluster_ids"]))
                if not opt["examples"]:
                    decisions.append({"question": q["text"], "answer": opt["label"]})
                    continue
                ex = opt["examples"][0]
                decisions.append({"question": q["text"], "answer": opt["label"],
                                  "example": f"{run['signature']['name']}(**{json.dumps(next(i for i in run['inputs'] if i['id'] == ex['input_id'])['args'])}) -> {ex['value_repr']}"})
            unknown = set(answers) - set(qs)
            if unknown:
                raise PipelineError(f"unknown question ids: {sorted(unknown)}")
            surv, exact = surviving_clusters(run["clusters"], chosen_sets)
            clusters = {c["id"]: c for c in run["clusters"]}
            best = max(surv, key=lambda c: clusters[c]["size"])
            chosen_impl = next(i for i in run["implementations"] if i["id"] == clusters[best]["representative_impl_id"])
            inputs = {i["id"]: i for i in run["inputs"]}
            locked = [{"input_id": iid, "args": inputs[iid]["args"], "expected_repr": outcome_key(o)}
                      for iid, o in chosen_impl["outcomes"].items() if iid not in overrides]
            expected = {c["input_id"]: c["expected_repr"] for c in locked}
            ex = {i["id"]: i["outcomes"] for i in run["implementations"] if i["status"] == "executed"}
            passed, n = agreement(ex, expected)
            run["status"] = "resolving"
            run["resolution"] = {
                "answers": {q["id"]: q.get("answer_option_id") for q in run["questions"]},
                "surviving_cluster_ids": surv, "exact_match": exact, "chosen_impl_id": chosen_impl["id"],
                "clarified_spec": "", "decisions": [f"{d['question']} → {d['answer']}" for d in decisions],
                "tests_code": "", "reference_code": chosen_impl["code"], "locked_cases": locked,
                "agreement_before": round(passed / n, 4) if n else 0.0, "agreement_before_counts": [passed, n],
                "unlocked_input_ids": sorted(overrides),
            }
            self._log(run, "resolve", f"Chosen behaviour {clusters[best]['label']}: {passed}/{n} original implementations already matched it")
            clarified = run["spec"]
            if decisions:
                try:
                    sig_name = run["signature"]["name"]
                    witness_ids = [w for q in run["questions"] for w in q["witness_input_ids"]]
                    ordered = witness_ids + [c["input_id"] for c in locked if c["input_id"] not in witness_ids]
                    by_id = {c["input_id"]: c for c in locked}
                    examples = [f"{sig_name}(**{json.dumps(by_id[i]['args'])}) -> {by_id[i]['expected_repr']}"
                                for i in dict.fromkeys(ordered) if i in by_id][:16]
                    raw = await self._json_call(run, "clarify", prompts.CLARIFY_SYSTEM,
                                                prompts.clarify_user(run["spec"], decisions, chosen_impl.get("code") or "", examples),
                                                model=run["settings"]["deep_model"], thinking=True, max_tokens=10000, temperature=0.3,
                                                template_kwargs={"medium_effort": True}, fallback_no_thinking=True)
                    clarified = str(raw.get("clarified_spec") or "").strip() or clarified
                    if raw.get("decisions"):
                        run["resolution"]["decisions"] = [str(d)[:240] for d in raw["decisions"]][:8]
                except (LLMError, PipelineError) as e:
                    clarified = run["spec"].strip() + "\n\nDecisions:\n" + "\n".join(f"- {d['question']} {d['answer']}" for d in decisions)
                    self._log(run, "resolve", f"Clarifier unavailable ({str(e)[:60]}); appended decisions verbatim")
            run["resolution"]["clarified_spec"] = clarified
            run["resolution"]["tests_code"] = render_tests(run["signature"], locked, clarified)
            run["status"] = "resolved"
            self._log(run, "resolve", f"Locked {len(locked)} executable test cases")
        except PipelineError as e:
            run["status"] = "awaiting_answers"
            run["error"] = str(e)
            self._log(run, "resolve", f"Could not resolve: {e}")
            raise
        finally:
            run["metrics"]["wall_time_s"] = round(run["metrics"]["wall_time_s"] + time.perf_counter() - t0, 2)

    # ---- converge
    async def converge(self, run: dict[str, Any], n_samples: int) -> None:
        t0 = time.perf_counter()
        res = run["resolution"]
        res["convergence"] = {"n": n_samples, "passed": 0, "agreement_after": 0.0, "clusters_after": 0, "status": "running",
                              "implementations": []}
        conv = res["convergence"]
        self._log(run, "converge", f"Re-forking the clarified spec: {n_samples} fresh implementations")
        try:
            impls = [{"id": f"r{k}", "index": k, "model": run["settings"]["fast_model"], "status": "pending"} for k in range(n_samples)]
            conv["implementations"] = impls
            base = int(hashlib.sha256(res["clarified_spec"].encode()).hexdigest()[:6], 16)
            await asyncio.gather(*(self._one_impl(run, impl, res["clarified_spec"], run["inputs"], base + impl["index"], "reimplement")
                                   for impl in impls))
            ex = {i["id"]: i["outcomes"] for i in impls if i["status"] == "executed"}
            expected = {c["input_id"]: c["expected_repr"] for c in res["locked_cases"]}
            passed, n = agreement(ex, expected)
            for i in impls:
                if i["status"] == "executed":
                    i["passes_locked"] = all(outcome_key(i["outcomes"].get(k)) == v for k, v in expected.items())
            cr = cluster_impls(ex, [i["id"] for i in run["inputs"]])
            conv.update({"passed": passed, "executed": n, "agreement_after": round(passed / n, 4) if n else 0.0,
                         "clusters_after": len(cr.clusters), "status": "done"})
            self._log(run, "converge", f"{passed}/{n} fresh implementations match your intent on every locked case "
                                       f"(before: {res['agreement_before_counts'][0]}/{res['agreement_before_counts'][1]})")
        except Exception as e:  # noqa: BLE001
            conv["status"] = "error"
            self._log(run, "converge", f"Convergence check failed: {str(e)[:120]}")
        finally:
            run["status"] = "resolved"
            run["metrics"]["wall_time_s"] = round(run["metrics"]["wall_time_s"] + time.perf_counter() - t0, 2)
            self.notify(run)


def summarize(run: dict[str, Any]) -> dict[str, Any]:
    return {"id": run["id"], "created_at": run["created_at"], "status": run["status"], "spec": run["spec"][:200],
            "n_clusters": len([c for c in run.get("clusters", []) if c.get("kind") == "behavior"]),
            "is_sample": run.get("is_sample", False), "preset_id": run.get("preset_id")}


__all__ = ["SpecFork", "new_run", "summarize", "render_tests", "canon", "PipelineError"]
