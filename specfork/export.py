"""Exports of a resolved run: machine-readable decision record (JSON or YAML) for committing next to code."""
from __future__ import annotations

import json
import re
from typing import Any

from . import __version__


def decision_record(run: dict[str, Any]) -> dict[str, Any]:
    res = run["resolution"]
    q_by_id = {q["id"]: q for q in run["questions"]}
    decisions = []
    for qid, oid in (res.get("answers") or {}).items():
        q = q_by_id.get(qid)
        if not q or not oid:
            continue
        opt = next((o for o in q["options"] if o["id"] == oid), None)
        decisions.append({"question": q["text"], "kind": q["kind"], "answer": opt["label"] if opt else oid,
                          "custom": bool(opt and opt.get("is_custom"))})
    return {
        "specfork_version": __version__, "run_id": run["id"], "spec": run["spec"],
        "clarified_spec": res["clarified_spec"], "signature": run["signature"], "decisions": decisions,
        "locked_cases": [{"args": c["args"], "expected": c["expected_repr"]} for c in res["locked_cases"]],
        "agreement_before": res["agreement_before"],
        "agreement_after": (res.get("convergence") or {}).get("agreement_after"),
        "models": {"fast": run["settings"]["fast_model"], "deep": run["settings"]["deep_model"]},
        "prompt_version": run["settings"].get("prompt_version"), "prompt_hash": run["settings"].get("prompt_hash"),
    }


_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .,/()-]*$")
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~", ""}


def _scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    s = str(v)
    if _PLAIN.match(s) and s.lower() not in _RESERVED and not s.endswith(" ") and ": " not in s:
        return s
    return json.dumps(s, ensure_ascii=False)  # a JSON string is a valid YAML double-quoted scalar


def to_yaml(value: Any, indent: int = 0) -> str:
    """Minimal YAML emitter for JSON-like data (dicts, lists, scalars); output parses with any YAML 1.2 parser."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return pad + "{}\n"
        out = []
        for k, v in value.items():
            key = _scalar(str(k))
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{key}:\n{to_yaml(v, indent + 1)}")
            elif isinstance(v, str) and "\n" in v:
                body = "\n".join(f"{pad}  {line}" for line in v.splitlines())
                out.append(f"{pad}{key}: |-\n{body}\n")
            else:
                out.append(f"{pad}{key}: {to_yaml(v, 0).strip() if isinstance(v, (dict, list)) else _scalar(v)}\n")
        return "".join(out)
    if isinstance(value, list):
        if not value:
            return pad + "[]\n"
        out = []
        for item in value:
            if isinstance(item, (dict, list)) and item:
                inner = to_yaml(item, indent + 1)
                out.append(f"{pad}- {inner.lstrip()}")
            else:
                out.append(f"{pad}- {_scalar(item) if not isinstance(item, (dict, list)) else to_yaml(item).strip()}\n")
        return "".join(out)
    return pad + _scalar(value) + "\n"
