"""SpecFork as an MCP server (stdio), so coding agents can check a spec for ambiguity before writing code.

Configure in an MCP client, e.g.::

    {"mcpServers": {"specfork": {"command": "uvx", "args": ["--from", "specfork[mcp] @ git+https://github.com/maestrosatyam/SpecFork", "specfork", "mcp"],
                                 "env": {"NEBIUS_API_KEY": "..."}}}}
"""
from __future__ import annotations

import os
from typing import Any

from .api import Client, ForkError
from .types import Run

INSTRUCTIONS = (
    "SpecFork finds the decisions a function spec leaves open. Call fork_spec with the user's spec BEFORE "
    "implementing it. Relay every returned question (with its executed examples) to the user and let THEM "
    "choose; do not answer on their behalf unless they ask you to. Then call answer, and use get_tests / "
    "get_clarified_spec as the contract for your implementation."
)

_runs: dict[str, dict[str, Any]] = {}
_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client()
    return _client


def _call(run: dict[str, Any], input_id: str) -> str:
    args = next(i["args"] for i in run["inputs"] if i["id"] == input_id)
    return f"{run['signature']['name']}(" + ", ".join(f"{k}={v!r}" for k, v in args.items()) + ")"


def _questions(run: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for q in run["questions"]:
        if q["kind"] not in ("ambiguity", "assumption"):
            continue
        out.append({
            "id": q["id"], "kind": q["kind"], "question": q["text"], "why": q.get("why", ""),
            "options": [{"id": o["id"], "answer": o["label"], "implementations": o.get("impl_count", 0),
                         "executed_examples": [f"{_call(run, e['input_id'])} -> {e['value_repr']}" for e in o["examples"][:2]],
                         **({"proposed_example": o["note"]} if o.get("note") else {})}
                        for o in q["options"]],
            "free_text_allowed": True,
        })
    return out


async def fork_spec(spec: str, n_samples: int = 16, assumptions: bool = True) -> dict[str, Any]:
    """Fork a natural-language function spec into independent implementations, execute them, and return the
    behaviours they disagree on as questions for the user (each option has real executed examples)."""
    from . import sandbox

    st = await sandbox.selftest()
    if not st.get("net_isolated") and os.environ.get("SPECFORK_ALLOW_WEAK_SANDBOX") != "1":
        return {"error": "Sandbox isolation is weak on this host; set SPECFORK_ALLOW_WEAK_SANDBOX=1 to allow it."}
    client = _get_client()
    try:
        run = await client.fork(spec, n_samples=max(4, min(40, n_samples)), assumptions=assumptions)
    except ForkError as e:
        return {"error": str(e)}
    raw = run.model_dump()
    _runs[raw["id"]] = raw
    return {
        "run_id": raw["id"],
        "signature": raw["signature"],
        "behaviours": [{"label": c["label"], "implementations": c["size"], "summary": c.get("summary")}
                       for c in raw["clusters"] if c["kind"] == "behavior"],
        "questions": _questions(raw),
        "cost_usd": raw["metrics"]["total_cost_usd"],
        "next_step": "Ask the user these questions, then call answer(run_id, answers={question_id: option_id}, "
                     "other={question_id: free text}).",
    }


async def list_questions(run_id: str) -> dict[str, Any]:
    """Return the open questions of a run created with fork_spec."""
    run = _runs.get(run_id)
    if run is None:
        return {"error": "unknown run_id"}
    return {"run_id": run_id, "questions": _questions(run)}


async def answer(run_id: str, answers: dict[str, str], other: dict[str, str] | None = None) -> dict[str, Any]:
    """Apply the user's answers (question id -> option id) and free-text answers (question id -> text).
    Returns the clarified spec and how many executable test cases were locked."""
    run = _runs.get(run_id)
    if run is None:
        return {"error": "unknown run_id"}
    client = _get_client()
    try:
        resolved: Run = await client.resolve(run, answers, other or {})
    except Exception as e:  # noqa: BLE001 - report pipeline errors to the agent
        return {"error": str(e)[:300]}
    _runs[run_id] = resolved.model_dump()
    res = resolved.resolution
    assert res is not None
    return {"run_id": run_id, "clarified_spec": res.clarified_spec, "decisions": res.decisions,
            "locked_cases": len(res.locked_cases), "agreement_before": res.agreement_before,
            "next_step": "Call get_tests(run_id, module=...) and implement against the clarified spec."}


async def get_tests(run_id: str, module: str = "solution") -> str:
    """Return a pytest file locking the chosen behaviour; it imports the function from `module`."""
    run = _runs.get(run_id)
    if run is None or not run.get("resolution"):
        return "error: unknown or unresolved run_id"
    return Client.tests(run, module=module)


async def get_clarified_spec(run_id: str) -> str:
    """Return the clarified spec text of a resolved run."""
    run = _runs.get(run_id)
    if run is None or not run.get("resolution"):
        return "error: unknown or unresolved run_id"
    return run["resolution"]["clarified_spec"]


async def refork(run_id: str, n_samples: int = 16) -> dict[str, Any]:
    """Re-implement the clarified spec from scratch and measure how many fresh implementations pass the locked tests."""
    run = _runs.get(run_id)
    if run is None or not run.get("resolution"):
        return {"error": "unknown or unresolved run_id"}
    r = await _get_client().converge(run, max(4, min(40, n_samples)))
    _runs[run_id] = r.model_dump()
    c = r.resolution.convergence if r.resolution else None
    return {"agreement_before": r.resolution.agreement_before if r.resolution else None,
            "agreement_after": c.agreement_after if c else None}


TOOLS = [fork_spec, list_questions, answer, get_tests, get_clarified_spec, refork]


def build_server():
    from mcp.server.mcpserver import MCPServer

    from . import __version__

    server = MCPServer(name="specfork", instructions=INSTRUCTIONS, version=__version__)
    for fn in TOOLS:
        server.tool()(fn)
    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
