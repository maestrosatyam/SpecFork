"""Scripted stand-in for Nebius Token Factory used by offline tests (never used in production)."""
from __future__ import annotations

import json
import re

import httpx

FRAME = {
    "name": "split_bill",
    "params": [{"name": "total", "type": "float", "description": "bill total"},
               {"name": "n", "type": "int", "description": "number of people"}],
    "returns": {"type": "list[float]", "description": "amount per person"},
    "inputs": [
        {"args": {"total": 100, "n": 3}, "note": "leftover cent"},
        {"args": {"total": 90, "n": 3}, "note": "even"},
        {"args": {"total": 10, "n": 0}, "note": "zero people"},
        {"args": {"total": 0.05, "n": 2}, "note": "tiny"},
        {"args": {"total": 50, "n": 1}, "note": "single"},
    ],
}

IMPLS = {
    # A: extra cents to first people (sums to total)
    "A": "def split_bill(total, n):\n    if n <= 0:\n        raise ValueError('n')\n    c = round(total * 100)\n    b, e = divmod(c, n)\n    return [(b + (1 if i < e else 0)) / 100 for i in range(n)]\n",
    # B: everyone pays the rounded share (cent lost)
    "B": "def split_bill(total, n):\n    if n <= 0:\n        raise ValueError('n')\n    return [round(total / n, 2)] * n\n",
    # C: round up everyone
    "C": "import math\ndef split_bill(total, n):\n    if n <= 0:\n        return []\n    return [math.ceil(total * 100 / n) / 100] * n\n",
    # unsafe implementation: must be rejected by the static check
    "X": "import os\ndef split_bill(total, n):\n    return os.listdir('/')\n",
}
ORDER = ["A", "A", "B", "A", "B", "C", "A", "X"]

EXPLAIN = {
    "cluster_summaries": {"A": "Gives leftover cents to the first people", "B": "Everyone pays the rounded share",
                          "C": "Rounds every share up"},
    "axes": [
        {"axis_id": "x0", "kind": "ambiguity", "question": "When the bill doesn't divide evenly, what happens to the leftover cents?",
         "why": "Shares may not add up to the bill.", "options": [{"group": "g0", "label": "First people pay one cent more"},
                                                               {"group": "g1", "label": "Everyone pays the rounded share"},
                                                               {"group": "g2", "label": "Round everyone up"}],
         "bug_groups": [], "merge_into": None},
    ],
}


def make_transport(counter: dict | None = None) -> httpx.MockTransport:
    state = {"impl": 0}
    counter = counter if counter is not None else {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        counter[body.get("model")] = counter.get(body.get("model"), 0) + 1
        if "design extra test inputs" in system:
            content = json.dumps({"inputs": [{"args": {"total": 100, "n": 7}, "note": "remainder 2"},
                                             {"args": {"total": 100, "n": 3}, "note": "already tried"}]})
            reasoning = None
        elif "differential testing" in system:
            content, reasoning = json.dumps(FRAME), "Need typed params; include remainder cases."
        elif "senior Python developer" in system:
            user = body["messages"][1]["content"]
            if "Clarified" in user or "first people" in user:
                key = "A"
            else:
                key = ORDER[state["impl"] % len(ORDER)]
                state["impl"] += 1
            content, reasoning = f"```python\n{IMPLS[key]}```", None
        elif "SILENT ASSUMPTIONS" in system:
            content = json.dumps({"assumptions": [{
                "question": "Should a $0 bill be split at all?", "why": "Zero bills may be data errors.",
                "consensus_label": "Everyone pays 0.0", "alternative_label": "Raise an error for a $0 bill",
                "input_ids": ["i999", "i3"], "alternative_example": "split_bill(0, 2) -> raises", "confidence": 0.9},
                {"question": "Trivial?", "why": "", "consensus_label": "x", "alternative_label": "y",
                 "input_ids": ["i1"], "alternative_example": "", "confidence": 0.2}]})
            reasoning = "All implementations return zeros."
        elif "requirements analyst" in system:
            content, reasoning = json.dumps(EXPLAIN), "Group g0 sums to total; others lose or add cents."
        elif "rewrite a function spec" in system:
            content = json.dumps({"clarified_spec": "Split a restaurant bill evenly among n people... Clarified: leftover cents go to the first people.",
                                  "decisions": ["Leftover cents go one each to the first people."]})
            reasoning = None
        elif "clarifying questions you would ask" in system:
            content, reasoning = json.dumps({"questions": ["What happens to leftover cents?"]}), "think"
        elif "product owner who wrote" in system:
            user = body["messages"][1]["content"]
            if "Options:" in user:
                ids = re.findall(r'"id": "(q[0-9]+g[0-9]+)"', user)
                content = json.dumps({"option": ids[0] if ids else "none"})
            else:
                content = json.dumps({"answers": [{"question": "What happens to leftover cents?", "answer": "first people pay extra"}]})
            reasoning = None
        else:
            return httpx.Response(400, text="unexpected prompt")
        msg = {"role": "assistant", "content": content}
        if reasoning:
            msg["reasoning_content"] = reasoning
        return httpx.Response(200, json={"id": "fake", "model": body["model"], "choices": [{"message": msg, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 50}})

    return httpx.MockTransport(handler)


def make_router(transport: httpx.MockTransport | None = None, key: str = "test", **kw):
    """ModelRouter over the built-in registry with a scripted transport (no network)."""
    from specfork.llm import ModelRouter
    from specfork.registry import Registry

    return ModelRouter(Registry.load(), {"NEBIUS_API_KEY": key}, transport=transport or make_transport(), **kw)
