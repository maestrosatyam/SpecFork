"""Prompt templates. Kept in one place so they can be audited and versioned."""
from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "2026-10-29.1"

FRAME_SYSTEM = """You prepare natural-language function specs for differential testing.
Given a spec, produce:
1. A precise Python function signature: snake_case name, typed parameters, return type.
   Use only these types: int, float, str, bool, None, list[...], dict[str, ...], Optional[...].
   Represent dates/times as ISO-8601 strings (e.g. "2024-02-29").
   IMPORTANT: never resolve ambiguity. Descriptions restate only what the spec says.
2. 14-18 probe inputs (keyword arguments as JSON) that a careful tester would try. Include typical
   cases AND the edge cases where reasonable developers might implement the spec differently:
   boundaries and ties, empty values, zero, rounding, case and whitespace, unicode, ordering,
   duplicates, leap years, inclusive/exclusive ranges, plausible-but-unusual values.
   Every input must be valid JSON and match the parameter types.
Reply with JSON only, no prose:
{"name": str, "params": [{"name": str, "type": str, "description": str}],
 "returns": {"type": str, "description": str},
 "inputs": [{"args": {<param>: <value>}, "note": "why this probe is interesting"}]}"""

FRAME_INPUTS_SYSTEM = """You prepare natural-language function specs for differential testing.
The function signature is fixed (given below). Produce 14-18 probe inputs (keyword arguments as JSON)
that a careful tester would try: typical cases AND the edge cases where reasonable developers might
implement the spec differently (boundaries and ties, empty values, zero, rounding, case and whitespace,
unicode, ordering, duplicates, leap years, inclusive/exclusive ranges, plausible-but-unusual values).
Every input must be valid JSON and match the parameter names and types exactly.
Reply with JSON only: {"inputs": [{"args": {<param>: <value>}, "note": "why this probe is interesting"}]}"""

IMPLEMENT_SYSTEM = """You are a senior Python developer. Implement the requested function.
Where the spec is silent or unclear, make the choice you personally consider most reasonable:
do not ask questions, do not hedge, do not add parameters, do not explain.
Use only the Python standard library (math, decimal, fractions, datetime, re, string, collections,
itertools, functools, statistics, unicodedata, calendar, heapq, bisect). No I/O, no printing.
Reply with exactly one ```python code block containing the function (helpers allowed)."""

EXPLAIN_SYSTEM = """You are a meticulous requirements analyst. Many independent developers implemented the
same spec. Their programs were executed and grouped by behaviour. You are shown inputs on which the
groups disagree, with each group's actual output and a representative implementation.

For each axis of disagreement decide:
- kind "ambiguity": the spec genuinely allows more than one reasonable behaviour. Write ONE short,
  plain-English clarifying question a non-programmer product owner can answer, a one-sentence "why"
  (the concrete consequence of picking wrong), and a short answer label (max ~12 words) for each group.
- kind "likely_bug": one group violates what the spec clearly says (e.g. crashes on a valid input,
  wrong arithmetic). Then list the buggy groups in "bug_groups" and still give labels.
If two axes are really the same underlying question, set "merge_into" on the later one to the earlier axis id.
Also give a <=14-word plain-English summary of what each cluster does differently.
Reply with JSON only:
{"cluster_summaries": {"<cluster label>": str},
 "axes": [{"axis_id": str, "kind": "ambiguity"|"likely_bug", "question": str, "why": str,
           "options": [{"group": str, "label": str}], "bug_groups": [str], "merge_into": str|null}]}"""

CLARIFY_SYSTEM = """You rewrite a function spec so it is unambiguous, given the product owner's decisions.
Keep the original wording and intent; add precise sentences that encode each decision (with a tiny
example where it helps). Do not add requirements that were not decided. Keep it under 150 words.
Reply with JSON only: {"clarified_spec": str, "decisions": [str]}"""


def signature_stub(sig: dict[str, Any]) -> str:
    params = ", ".join(f"{p['name']}: {p['type']}" for p in sig["params"])
    doc_lines = [f"    {p['name']}: {p['description']}" for p in sig["params"]]
    doc_lines.append(f"    returns: {sig['returns']['description']}")
    doc = "\n".join(doc_lines)
    return f'def {sig["name"]}({params}) -> {sig["returns"]["type"]}:\n    """\n{doc}\n    """\n    ...'


def implement_user(spec: str, sig: dict[str, Any]) -> str:
    return (
        f"Spec:\n{spec.strip()}\n\nSignature (keep exactly this name and these parameters):\n"
        f"```python\n{signature_stub(sig)}\n```"
    )


def frame_user(spec: str, sig: dict[str, Any] | None = None) -> str:
    if sig:
        return f"Spec:\n{spec.strip()}\n\nFixed signature:\n```python\n{signature_stub(sig)}\n```"
    return f"Spec:\n{spec.strip()}"


def explain_user(spec: str, sig: dict[str, Any], axes_payload: list[dict[str, Any]], clusters_payload: list[dict[str, Any]]) -> str:
    return (
        f"Spec:\n{spec.strip()}\n\nSignature:\n```python\n{signature_stub(sig)}\n```\n\n"
        f"Clusters (label, number of implementations, representative code):\n{json.dumps(clusters_payload, indent=1)}\n\n"
        f"Axes of disagreement:\n{json.dumps(axes_payload, indent=1)}"
    )


def clarify_user(spec: str, decisions: list[dict[str, str]]) -> str:
    return f"Original spec:\n{spec.strip()}\n\nDecisions:\n{json.dumps(decisions, indent=1)}"
