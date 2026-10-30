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
   Use ONLY parameters the spec mentions or directly implies; never invent extra options (no tips, flags, modes).
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
  (the concrete consequence of picking wrong), and for each group an answer "label": a short
  human-readable sentence (max ~12 words, e.g. "The first people pay one extra cent each"), never an identifier.
- kind "likely_bug": ONLY when one group violates something the spec explicitly states (e.g. crashes on a
  clearly valid input, wrong arithmetic). Behaviour the spec does not mention (invalid inputs, zero, empty,
  rounding modes, ordering) is an "ambiguity", not a bug. List buggy groups in "bug_groups"; still give labels.
If two axes are really the same underlying question, set "merge_into" on the later one to the earlier axis id.
Also give a <=14-word plain-English summary of what each cluster does differently.
Reply with JSON only:
{"cluster_summaries": {"<cluster label>": str},
 "axes": [{"axis_id": str, "kind": "ambiguity"|"likely_bug", "question": str, "why": str,
           "options": [{"group": str, "label": str}], "bug_groups": [str], "merge_into": str|null}]}"""

ASSUME_SYSTEM = """You are a meticulous requirements analyst. Many independent developers implemented the same
spec and most of them converged on one behaviour, shown below as a representative implementation plus its
ACTUAL executed outputs on probe inputs. Agreement does not mean the spec is clear: developers often share
the same silent default (US date order, Python rounding, inclusive ranges, case handling, what zero means).

List at most 3 SILENT ASSUMPTIONS: consequential decisions the spec never states, that this behaviour makes
one particular way, where a reasonable product owner could want the opposite. Skip anything already covered
by the open questions listed, anything the spec states explicitly, and trivia. For each give:
- "question": one plain-English question for a non-programmer product owner
- "why": one sentence on the concrete consequence
- "consensus_label": short sentence describing what the implementations do (max ~12 words)
- "alternative_label": short sentence describing the most plausible alternative (max ~12 words)
- "input_ids": ids of probe inputs whose output would change under the alternative (may be empty)
- "alternative_example": one example call and the output the alternative would give, e.g. "f('03/04/2025') -> '2025-04-03'"
Return an empty list if nothing important is left implicit. Reply with JSON only:
{"assumptions": [{"question": str, "why": str, "consensus_label": str, "alternative_label": str,
                  "input_ids": [str], "alternative_example": str}]}"""

CLARIFY_SYSTEM = """You rewrite a function spec so it is unambiguous on the points the product owner decided.
Input: the original spec, the owner's decisions (question -> chosen answer), and executed examples of the
chosen behaviour on exactly the inputs those decisions were about ("raises" means an exception).
Rules:
- Keep the original wording; add one precise sentence per decision, consistent with its examples.
- Encode ONLY the decisions. Do not describe incidental details nobody decided (exception class names,
  validation of types, behaviour on inputs not mentioned, implementation steps or algorithms).
- Include at most two tiny examples, taken from the list. Never mention code, implementations or clusters.
- Keep it under 110 words.
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


def assume_user(spec: str, sig: dict[str, Any], code: str, outputs: list[dict[str, Any]], n_agree: int, n_total: int,
                open_questions: list[str]) -> str:
    return (
        f"Spec:\n{spec.strip()}\n\nSignature:\n```python\n{signature_stub(sig)}\n```\n\n"
        f"{n_agree} of {n_total} implementations behave exactly like this one:\n```python\n{code[:2500]}\n```\n\n"
        f"Its executed outputs (input id, arguments, output; 'raises' = exception):\n{json.dumps(outputs, indent=0)}\n\n"
        f"Open questions already being asked:\n{json.dumps(open_questions, indent=1)}"
    )


def clarify_user(spec: str, decisions: list[dict[str, str]], chosen_code: str = "", examples: list[str] | None = None) -> str:
    out = f"Original spec:\n{spec.strip()}\n\nDecisions:\n{json.dumps(decisions, indent=1)}"
    if examples:
        out += "\n\nExecuted examples of the chosen behaviour:\n" + "\n".join(examples)
    if chosen_code:
        out += f"\n\nChosen implementation (for your understanding only):\n```python\n{chosen_code[:2500]}\n```"
    return out
