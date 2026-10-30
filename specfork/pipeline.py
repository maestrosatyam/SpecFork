"""SpecFork orchestration: frame → fan-out → execute → cluster → explain → resolve → converge.

Model roles (profiles from the registry; defaults: NVIDIA Nemotron on Nebius Token Factory):
  * fast model (default NVIDIA Nemotron 3.5 Lightning): framing, many independent implementations (cheap, high throughput)
  * deep model (default NVIDIA Nemotron 3 Ultra, reasoning on): explaining disagreements, rewriting the spec
Everything that decides (clustering, witnesses, tests, agreement) is deterministic code.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import time
from collections.abc import Callable
from typing import Any

from . import prompts
from .canon import canon
from .cluster import agreement, cluster_impls, find_axes, outcome_key, surviving_clusters
from .llm import CallRecord, LLMError, ModelRouter, extract_json
from .sandbox import check_code, exec_semaphore, run_function

IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")
MAX_INPUTS = 24
CONSENSUS_SHARE = 0.75
ASSUMPTION_MIN_CONFIDENCE = 0.6
MAX_ASSUMPTIONS = 2


def _conf(a: dict[str, Any]) -> float:
    try:
        return max(0.0, min(1.0, float(a.get("confidence", 0.0))))
    except (TypeError, ValueError):
        return 0.0


class PipelineError(RuntimeError):
    pass


# ---------------------------------------------------------------- helpers

def now() -> float:
    return round(time.time(), 3)


DEFAULT_FAST = "nvidia/Nemotron-3_5-Lightning"
DEFAULT_DEEP = "nvidia/Nemotron-3-Ultra-550b-a55b"


def new_run(run_id: str, spec: str, n_samples: int, preset_id: str | None = None,
            fast_model: str = DEFAULT_FAST, deep_model: str = DEFAULT_DEEP, *,
            implementers: list[str] | None = None, assumptions: bool = True,
            exception_types: bool = False) -> dict[str, Any]:
    """A fresh run record. Model arguments are model ids (or registry keys) resolved by the ModelRouter."""
    t = now()
    return {
        "id": run_id, "created_at": t, "updated_at": t, "status": "running", "stage": "frame",
        "spec": spec, "preset_id": preset_id, "is_sample": False,
        "settings": {"n_samples": n_samples, "fast_model": fast_model, "deep_model": deep_model,
                     "implementers": list(implementers or [fast_model]), "assumptions": assumptions,
                     "exception_types": exception_types,
                     "prompt_version": prompts.PROMPT_VERSION, "prompt_hash": prompts.prompt_hash()},
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
    if isinstance(raw.get("signature"), dict):  # tolerate {"signature": {...}, "inputs": [...]}
        raw = {**raw["signature"], **{k: v for k, v in raw.items() if k != "signature"}}
    for p in raw.get("params") or raw.get("parameters") or raw.get("args") or []:
        if not isinstance(p, dict):
            continue
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


def render_tests(sig: dict[str, Any], cases: list[dict[str, Any]], spec: str, module: str = "solution") -> str:
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

from {module} import {fname}  # noqa: E402

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
    elif expected.startswith(RAISES + ":"):
        with pytest.raises(Exception) as err:
            {fname}(**args)
        assert type(err.value).__name__ == expected.split(":", 1)[1]
    else:
        assert canon({fname}(**args)) == expected
'''


# ---------------------------------------------------------------- pipeline

class SpecFork:
    def __init__(self, client: ModelRouter, notify: Callable[[dict[str, Any]], None], *, frame_thinking: bool = False,
                 assumption_min_confidence: float = ASSUMPTION_MIN_CONFIDENCE, max_assumptions: int = MAX_ASSUMPTIONS) -> None:
        self.frame_thinking = frame_thinking
        self.assumption_min_confidence = assumption_min_confidence
        self.max_assumptions = max_assumptions
        self.client = client
        self.notify = notify

    def _log(self, run: dict[str, Any], stage: str, msg: str) -> None:
        run["log"].append({"t": now(), "stage": stage, "msg": msg[:400]})
        del run["log"][:-200]
        run["updated_at"] = now()
        self.notify(run)

    def _system(self, name: str, model: str, default: str) -> str:
        """System prompt ``name`` (frame, implement, explain, assumptions, clarify), overridable per model profile."""
        try:
            return self.client.profile(model).prompts.get(name, default)
        except Exception:  # noqa: BLE001 - unknown model: use the default prompt
            return default

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
                         effort=None, fallback_no_thinking=False):
        last: Exception | None = None
        for attempt in range(retries + 1):
            think = thinking and not (fallback_no_thinking and attempt > 0)
            system = self._system(purpose, model, system)
            res = await self._chat(run, purpose, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                                   model=model, thinking=think, max_tokens=max_tokens, temperature=temperature,
                                   effort=effort if think else None, json_mode=True)
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
                                    model=run["settings"]["fast_model"], thinking=self.frame_thinking, max_tokens=8000, temperature=0.4,
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
            res = await self._chat(run, purpose, [{"role": "system", "content": self._system("implement", impl["model"], prompts.IMPLEMENT_SYSTEM)},
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
            if run["settings"].get("exception_types"):
                for o in ex.outcomes.values():
                    if not o.get("ok"):
                        o["value_repr"] = f"raises:{o.get('error_type') or 'Exception'}"
            impl["status"], impl["outcomes"] = "executed", ex.outcomes
        self.notify(run)

    async def fanout(self, run: dict[str, Any]) -> None:
        run["stage"] = "fanout"
        n = run["settings"]["n_samples"]
        implementers = run["settings"].get("implementers") or [run["settings"]["fast_model"]]
        run["implementations"] = [{"id": f"m{k}", "index": k, "model": implementers[k % len(implementers)], "status": "pending"}
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
        cost: dict[str, float] = {i["id"]: float(len(json.dumps(i["args"]))) for i in run["inputs"]}
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
                                        effort="medium", fallback_no_thinking=True)
        except (LLMError, PipelineError) as e:
            self._log(run, "explain", f"Explainer unavailable ({str(e)[:80]}); using raw witness questions")
            raw = {"axes": []}
        if not isinstance(raw, dict):
            raw = {"axes": []}
        by_label = {c["label"]: c for c in run["clusters"]}
        summaries = raw.get("cluster_summaries")
        for lab, summ in (summaries.items() if isinstance(summaries, dict) else []):
            if lab in by_label:
                by_label[lab]["summary"] = str(summ)[:160]
        expl = {a.get("axis_id"): a for a in raw.get("axes") or [] if isinstance(a, dict)}
        questions = []
        for k, (ax, gmap) in enumerate(zip(axes, group_maps, strict=False)):
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
        if not run["settings"].get("assumptions", True):
            return
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
                                        effort="medium", fallback_no_thinking=True)
        except (LLMError, PipelineError) as e:
            self._log(run, "explain", f"Assumption review unavailable ({str(e)[:80]})")
            return
        valid_ids = {i["id"] for i in run["inputs"]}
        added = 0
        cands = [a for a in (raw.get("assumptions") or []) if isinstance(a, dict)]
        cands.sort(key=lambda a: -_conf(a))
        for k, a in enumerate(cands):
            if added >= self.max_assumptions:
                break
            if not a.get("question") or not a.get("alternative_label") or _conf(a) < self.assumption_min_confidence:
                continue
            affected = [i for i in (a.get("input_ids") or []) if isinstance(i, str) and i in valid_ids]
            if not affected:
                continue  # must be backed by at least one executed probe whose output would change
            # clusters that behave like the majority on the affected inputs keep the assumption
            keep_ids = [c["id"] for c in live
                        if all(outcome_key(impls[c["representative_impl_id"]]["outcomes"].get(i)) == outcome_key(rep["outcomes"].get(i))
                               for i in affected)]
            qid = f"a{k}"
            run["questions"].append({
                "id": qid, "kind": "assumption",
                "text": str(a["question"])[:300], "why": str(a.get("why") or "")[:300],
                "witness_input_ids": affected[:3], "affected_input_ids": affected,
                "agree_count": sum(c["size"] for c in live if c["id"] in keep_ids), "confidence": round(_conf(a), 2),
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
            run["status"], run["error"] = "error", f"internal error ({type(e).__name__})"
        finally:
            run["metrics"]["wall_time_s"] = round(run["metrics"]["wall_time_s"] + time.perf_counter() - t0, 2)
            self._log(run, run["stage"], "Ready for your answers" if run["status"] == "awaiting_answers" else f"Stopped: {run.get('error')}")

    # ---- resolve
    async def resolve(self, run: dict[str, Any], answers: dict[str, str], other: dict[str, str] | None = None) -> None:
        """Apply the owner's answers. ``answers`` maps question id -> option id; ``other`` maps question id ->
        free text for answers no sampled implementation produced (the deep model implements them, and the
        implementation is executed so the custom answer is backed by real outputs like every other option)."""
        t0 = time.perf_counter()
        other = {k: v for k, v in (other or {}).items() if v}
        try:
            qs = {q["id"]: q for q in run["questions"]}
            unknown = (set(answers) | set(other)) - set(qs)
            if unknown:
                raise PipelineError(f"{len(unknown)} unknown question id(s)")
            sig_name = run["signature"]["name"]
            inputs = {i["id"]: i for i in run["inputs"]}
            chosen_sets, decisions = [], []
            overrides: set[str] = set()
            custom_qs: list[dict[str, Any]] = []
            for q in run["questions"]:
                # drop a custom option from an earlier resolution of this run
                q["options"] = [o for o in q["options"] if not o.get("is_custom")]
                if q["id"] in other and q["kind"] in ("ambiguity", "assumption"):
                    custom_qs.append(q)  # its executed implementation reflects the answer: nothing to unlock
                    decisions.append({"question": q["text"], "answer": other[q["id"]],
                                      "note": "Free-text answer from the product owner; no sampled implementation did this."})
                    continue
                oid = answers.get(q["id"]) or (q.get("answer_option_id") if q["kind"] == "likely_bug" else None)
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
                if q["kind"] == "likely_bug":
                    continue  # excludes the buggy behaviour, but is not a product decision
                if not opt["examples"]:
                    decisions.append({"question": q["text"], "answer": opt["label"]})
                    continue
                ex0 = opt["examples"][0]
                decisions.append({"question": q["text"], "answer": opt["label"],
                                  "example": f"{sig_name}(**{json.dumps(inputs[ex0['input_id']]['args'])}) -> {ex0['value_repr']}"})
            surv, exact = surviving_clusters(run["clusters"], chosen_sets)
            clusters = {c["id"]: c for c in run["clusters"]}
            best = max(surv, key=lambda c: clusters[c]["size"])
            base_impl = next(i for i in run["implementations"] if i["id"] == clusters[best]["representative_impl_id"])
            ex = {i["id"]: i["outcomes"] for i in run["implementations"]
                  if i["status"] == "executed" and not i["id"].startswith("u")}
            custom_ids = {q["id"] for q in custom_qs}
            decided_option_ids = {q["id"] for q in run["questions"] if q["kind"] != "likely_bug" and q["id"] not in custom_ids
                                  and q.get("answer_option_id")
                                  and not any(o.get("is_alternative") and o["id"] == q["answer_option_id"] for o in q["options"])}
            witness_ids = [w for q in run["questions"] if q["id"] in decided_option_ids for w in q["witness_input_ids"]]
            run["status"] = "resolving"

            # 1. clarified spec (encodes only the decided points)
            clarified = run["spec"]
            if decisions:
                examples = [f"{sig_name}(**{json.dumps(inputs[i]['args'])}) -> {outcome_key(base_impl['outcomes'].get(i))}"
                            for i in dict.fromkeys(witness_ids) if i not in overrides][:10]
                try:
                    raw = await self._json_call(run, "clarify", prompts.CLARIFY_SYSTEM,
                                                prompts.clarify_user(run["spec"], decisions, "", examples),
                                                model=run["settings"]["deep_model"], thinking=True, max_tokens=10000,
                                                temperature=0.3, effort="medium", fallback_no_thinking=True)
                    clarified = str(raw.get("clarified_spec") or "").strip() or clarified
                    decision_lines = [str(d)[:240] for d in (raw.get("decisions") or [])][:8]
                except (LLMError, PipelineError) as e:
                    clarified = run["spec"].strip() + "\n\nDecisions:\n" + "\n".join(f"- {d['question']} {d['answer']}" for d in decisions)
                    decision_lines = []
                    self._log(run, "resolve", f"Clarifier unavailable ({str(e)[:60]}); appended decisions verbatim")
            else:
                decision_lines = []

            # 2. reference implementation: the chosen cluster, or a new executed implementation of custom answers
            chosen_impl = base_impl
            if custom_qs:
                self._log(run, "resolve", f"Implementing your own answer(s) with {run['settings']['deep_model']} and executing them")
                custom = None
                for k, model in enumerate((run["settings"]["deep_model"], run["settings"]["fast_model"])):
                    impl = {"id": f"u{k}", "index": len(run["implementations"]), "model": model, "status": "pending"}
                    seed = int(hashlib.sha256(clarified.encode()).hexdigest()[:6], 16)
                    await self._one_impl(run, impl, clarified, run["inputs"], seed, "implement_custom")
                    if impl["status"] == "executed":
                        custom = impl
                        break
                if custom is None:
                    raise PipelineError("could not turn your free-text answer into a working implementation; "
                                        "try rephrasing it or pick one of the options")
                run["implementations"].append(custom)
                chosen_impl = custom
                for q in custom_qs:
                    opt = {"id": f"{q['id']}other", "label": other[q["id"]][:140], "is_custom": True, "cluster_ids": [],
                           "impl_count": 0,
                           "examples": [{"input_id": w, "value_repr": outcome_key(custom["outcomes"].get(w))}
                                        for w in (q["witness_input_ids"] or q.get("affected_input_ids") or [])[:3]]}
                    q["options"].append(opt)
                    q["answer_option_id"] = opt["id"]

            # 3. lock only what was decided or what the original implementations already agreed on (>= 75%)
            decided = set(witness_ids) | {w for q in custom_qs for w in (q["witness_input_ids"] or [])}
            locked, left_open = [], []
            for iid, o in chosen_impl["outcomes"].items():
                if iid in overrides:
                    continue  # an overridden assumption: no implementation produced the wanted output
                key = outcome_key(o)
                share = sum(1 for per in ex.values() if outcome_key(per.get(iid)) == key) / max(1, len(ex))
                if iid in decided or share >= CONSENSUS_SHARE:
                    locked.append({"input_id": iid, "args": inputs[iid]["args"], "expected_repr": key,
                                   "basis": "decided" if iid in decided else "consensus"})
                else:
                    left_open.append(iid)
            expected = {c["input_id"]: c["expected_repr"] for c in locked}
            passed, n = agreement(ex, expected)
            run["resolution"] = {
                "answers": {q["id"]: q.get("answer_option_id") for q in run["questions"]},
                "surviving_cluster_ids": surv, "exact_match": exact, "chosen_impl_id": chosen_impl["id"],
                "custom_impl_id": chosen_impl["id"] if custom_qs else None,
                "clarified_spec": clarified,
                "decisions": decision_lines or [f"{d['question']} → {d['answer']}" for d in decisions],
                "tests_code": render_tests(run["signature"], locked, clarified), "reference_code": chosen_impl["code"],
                "locked_cases": locked,
                "agreement_before": round(passed / n, 4) if n else 0.0, "agreement_before_counts": [passed, n],
                "unlocked_input_ids": sorted(overrides), "open_input_ids": left_open,
            }
            run["status"] = "resolved"
            label = "your own answer" if custom_qs else f"behaviour {clusters[best]['label']}"
            self._log(run, "resolve", f"Chosen {label}: {passed}/{n} original implementations already matched it")
            self._log(run, "resolve", f"Locked {len(locked)} executable test cases ({len(left_open)} undecided case(s) left open)")
        except PipelineError as e:
            run["status"] = "awaiting_answers"
            run["error"] = str(e)[:300]
            self._log(run, "resolve", f"Could not resolve: {str(e)[:200]}")
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
            implementers = run["settings"].get("implementers") or [run["settings"]["fast_model"]]
            impls = [{"id": f"r{k}", "index": k, "model": implementers[k % len(implementers)], "status": "pending"}
                     for k in range(n_samples)]
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
