"""``specfork`` command line.

    specfork fork "Split a bill evenly among n people, rounded to cents."     # interactive
    specfork fork --json "…" > run.json                                         # questions as JSON
    specfork resolve run.json --answers answers.json --module billing --out tests/
    specfork doctor                                                             # check models + sandbox
    specfork serve                                                              # web UI + HTTP API
    specfork mcp                                                                # MCP server (stdio)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__, sandbox
from .api import Client, ForkError
from .config import Settings
from .types import Run


def _p(msg: str = "", *, err: bool = False) -> None:
    print(msg, file=sys.stderr if err else sys.stdout, flush=True)


async def _require_sandbox(allow_weak: bool, quiet: bool) -> None:
    st = await sandbox.selftest()
    if not st.get("ok"):
        raise SystemExit(f"sandbox self-test failed: {st.get('error')}")
    if not st.get("net_isolated"):
        msg = ("Sandbox isolation is WEAK on this host: model-written code would run without a network namespace "
               "(macOS, Windows, or unprivileged user namespaces disabled).")
        if not allow_weak:
            raise SystemExit(msg + " Re-run with --allow-weak-sandbox to accept the risk, or use Linux/Docker.")
        if not quiet:
            _p("warning: " + msg, err=True)


def _call(run: Run, input_id: str) -> str:
    args = next(i.args for i in run.inputs if i.id == input_id)
    name = run.signature.name if run.signature else "f"
    return f"{name}(" + ", ".join(f"{k}={v!r}" for k, v in args.items()) + ")"


def print_run(run: Run) -> None:
    sig = run.signature
    if sig:
        _p(f"\ndef {sig.name}({', '.join(f'{p.name}: {p.type}' for p in sig.params)}) -> {sig.returns.get('type')}")
    executed = sum(1 for i in run.implementations if i.status == "executed")
    _p(f"{executed} implementations ran on {len(run.inputs)} probes → {len(run.behaviours)} distinct behaviour(s)  "
       f"[{run.metrics.n_calls} model calls, ${run.metrics.total_cost_usd:.4f}]")
    for c in run.behaviours:
        _p(f"  {c.label}  {c.size:>2} impl ({c.share:.0%})  {c.summary or ''}")


def ask(run: Run) -> tuple[dict[str, str], dict[str, str]]:
    answers: dict[str, str] = {}
    other: dict[str, str] = {}
    for n, q in enumerate(run.open_questions, 1):
        tag = "Silent assumption" if q.kind == "assumption" else "Question"
        _p(f"\n{tag} {n}: {q.text}")
        if q.why:
            _p(f"  why it matters: {q.why}")
        for k, o in enumerate(q.options, 1):
            _p(f"  [{k}] {o.label}" + (f"  ({o.impl_count} impl)" if o.impl_count else "  (proposed, not executed)"))
            for e in o.examples[:2]:
                _p(f"        {_call(run, e.input_id)} -> {e.value_repr}")
        _p("  [o] Other… (describe the behaviour you want)")
        while True:
            choice = input("  your answer: ").strip().lower()
            if choice == "o":
                text = input("  describe it: ").strip()
                if 3 <= len(text) <= 300:
                    other[q.id] = text
                    break
            elif choice.isdigit() and 1 <= int(choice) <= len(q.options):
                answers[q.id] = q.options[int(choice) - 1].id
                break
            _p("  please enter an option number or 'o'")
    return answers, other


def load_answers(path: str) -> tuple[dict[str, str], dict[str, str]]:
    """answers.json: {"q0": "q0g1", "a0": {"other": "raise ValueError for negative totals"}}"""
    data = json.loads(Path(path).read_text())
    answers = {k: v for k, v in data.items() if isinstance(v, str)}
    other = {k: v["other"] for k, v in data.items() if isinstance(v, dict) and "other" in v}
    return answers, other


def auto_answers(run: Run) -> dict[str, str]:
    """Pick, for every question, the compatible option chosen by most implementations (keeps assumptions)."""
    from .cluster import compatible_option_ids

    raw = run.model_dump()
    answers: dict[str, str] = {}
    for q in raw["questions"]:
        if q["kind"] not in ("ambiguity", "assumption"):
            continue
        ok = set(compatible_option_ids(raw["questions"], answers, q["id"], raw["clusters"]))
        cands = [o for o in q["options"] if o["id"] in ok and not o.get("is_alternative")] or q["options"]
        answers[q["id"]] = max(cands, key=lambda o: o.get("impl_count", 0))["id"]
    return answers


def write_outputs(client: Client, run: Run, out_dir: str | None, module: str, reference: str | None,
                  decision_file: str | None = None) -> list[str]:
    written = []
    if decision_file and run.resolution:
        from .export import decision_record, to_yaml

        rec = decision_record(run.model_dump())
        text = json.dumps(rec, indent=1) if decision_file.endswith(".json") else to_yaml(rec)
        Path(decision_file).write_text(text)
        written.append(decision_file)
    if out_dir is not None and run.resolution and run.signature:
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"test_{run.signature.name}.py"
        f.write_text(client.tests(run, module=module))
        written.append(str(f))
    if reference and run.resolution and run.resolution.reference_code:
        Path(reference).write_text(run.resolution.reference_code + "\n")
        written.append(reference)
    return written


async def cmd_fork(a: argparse.Namespace) -> int:
    settings = Settings.load()
    spec = a.spec if a.spec != "-" else sys.stdin.read()
    await _require_sandbox(a.allow_weak_sandbox, a.json)
    async with Client(settings) as client:
        if not a.json:
            _p(f"Forking with {client.registry.get(a.fast or settings.fast_model).display} "
               f"(explanations: {client.registry.get(a.deep or settings.deep_model).display})…")
        t0 = time.perf_counter()
        try:
            run = await client.fork(spec, n_samples=a.n, fast_model=a.fast, deep_model=a.deep,
                                    assumptions=not a.no_assumptions, exception_types=a.exception_types or None)
        except ForkError as e:
            _p(f"error: {e}", err=True)
            return 1
        if a.json and not (a.answers or a.auto):
            print(run.model_dump_json(indent=1))
            return 0
        if not a.json:
            print_run(run)
            _p(f"({time.perf_counter() - t0:.1f}s)")
        if a.answers:
            answers, other = load_answers(a.answers)
        elif a.auto:
            answers, other = auto_answers(run), {}
        elif run.open_questions:
            answers, other = ask(run)
        else:
            answers, other = {}, {}
        run = await client.resolve(run, answers, other)
        if a.refork:
            run = await client.converge(run, a.n)
        written = write_outputs(client, run, a.out, a.module, a.reference, a.decision_file)
        if a.json:
            print(run.model_dump_json(indent=1))
            return 0
        _summary(run, written)
    return 0


async def cmd_resolve(a: argparse.Namespace) -> int:
    run = Run.model_validate(json.loads(Path(a.run).read_text()))
    if a.answers:
        answers, other = load_answers(a.answers)
    elif a.auto:
        answers, other = auto_answers(run), {}
    else:
        answers, other = ask(run)
    await _require_sandbox(a.allow_weak_sandbox, a.json)
    async with Client(Settings.load()) as client:
        run = await client.resolve(run, answers, other)
        if a.refork:
            run = await client.converge(run)
        written = write_outputs(client, run, a.out, a.module, a.reference, a.decision_file)
    if a.json:
        print(run.model_dump_json(indent=1))
    else:
        _summary(run, written)
    return 0


def _summary(run: Run, written: list[str]) -> None:
    res = run.resolution
    if not res:
        return
    _p("\nClarified spec:\n  " + res.clarified_spec.replace("\n", "\n  "))
    _p(f"\nLocked {len(res.locked_cases)} test case(s); {len(res.open_input_ids)} undecided case(s) left open.")
    _p(f"Agreement with your intent before: {res.agreement_before:.0%}"
       + (f", after re-fork: {res.convergence.agreement_after:.0%}" if res.convergence else ""))
    for w in written:
        _p(f"wrote {w}")


async def cmd_doctor(a: argparse.Namespace) -> int:
    """Check every model profile used by the current settings (plus --all for every profile with a key)."""
    from .llm import LLMError, ModelRouter, extract_json
    from .registry import Registry

    settings = Settings.load()
    registry = Registry.load(settings.models_file)
    router = ModelRouter(registry, settings.api_keys, max_retries=1)
    keys = ([k for k in registry.profiles] if a.all else
            list(dict.fromkeys([settings.fast_model, settings.deep_model, *settings.implementer_keys])))
    failures = 0
    st = await sandbox.selftest()
    _p(f"sandbox: {'ok' if st.get('ok') else 'FAILED'}; network isolation: {'yes' if st.get('net_isolated') else 'NO (weak)'}")
    for key in keys:
        p = registry.get(key)
        row: dict[str, Any] = {"profile": p.key, "model": p.model, "api": p.api,
                               "price": "yes" if p.price_per_m else "MISSING"}
        if not router.configured(key):
            row["reachable"] = f"no key ({p.key_env})"
            _p("  " + json.dumps(row))
            failures += 1
            continue
        msgs = [{"role": "user", "content": 'What is 17 * 23? Reply with JSON {"answer": <number>} only.'}]
        try:
            r = await router.chat(msgs, model=key, max_tokens=200, temperature=0.0, json_mode=True)
            row["reachable"] = f"yes ({r.record.latency_s:.2f}s)"
            try:
                row["json"] = "yes" if extract_json(r.content).get("answer") == 391 else "wrong answer"
            except (ValueError, AttributeError):
                row["json"] = "NO"
            if p.seed:
                s1 = await router.chat([{"role": "user", "content": "Name a random fruit."}], model=key, temperature=1.0, seed=7, max_tokens=20)
                s2 = await router.chat([{"role": "user", "content": "Name a random fruit."}], model=key, temperature=1.0, seed=7, max_tokens=20)
                row["seed"] = "honoured" if s1.content == s2.content else "not deterministic"
            if p.reasoning != "none":
                t = await router.chat(msgs, model=key, thinking=True, effort="low", max_tokens=4000, temperature=0.6)
                row["reasoning"] = "toggles" if t.reasoning and not r.reasoning else "no separate reasoning"
        except LLMError as e:
            row["reachable"] = f"NO: {str(e)[:120]}"
            failures += 1
        _p("  " + json.dumps(row))
    await router.aclose()
    return 1 if failures else 0


def questions_markdown(run: Run, title: str) -> str:
    """PR/issue comment body listing the open questions with their executed witnesses."""
    lines = [f"### SpecFork: `{title}` has {len(run.behaviours)} meaning(s)", ""]
    if not run.open_questions:
        lines.append("All sampled implementations agree on every probe. No open questions.")
    for n, q in enumerate(run.open_questions, 1):
        lines += [f"**{'Assumption' if q.kind == 'assumption' else 'Q'}{n}. {q.text}** (`{q.id}`)", ""]
        for o in q.options:
            ex = "; ".join(f"`{_call(run, e.input_id)} → {e.value_repr}`" for e in o.examples[:2])
            lines.append(f"- `{o.id}` {o.label}" + (f" ({o.impl_count} impl) {ex}" if o.impl_count else " (proposed, not executed)"))
        lines.append("")
    lines += ["Answer by committing `<spec>.answers.json` next to the saved run, e.g. "
              '`{"q0": "q0g1", "a0": {"other": "describe the behaviour you want"}}`.', ""]
    return "\n".join(lines)


async def cmd_ci(a: argparse.Namespace) -> int:
    """Ambiguity check for a repository: fork new specs, resolve answered ones, report open questions."""
    import glob

    specs = sorted({p for pat in a.specs for p in glob.glob(pat, recursive=True)})
    state = Path(a.state)
    state.mkdir(parents=True, exist_ok=True)
    comment: list[str] = []
    open_count = 0
    await _require_sandbox(a.allow_weak_sandbox, True)
    async with Client(Settings.load()) as client:
        for spec_path in specs:
            name = Path(spec_path).stem
            run_file, answers_file = state / f"{name}.run.json", state / f"{name}.answers.json"
            run: Run | None = None
            if run_file.exists():
                run = Run.model_validate(json.loads(run_file.read_text()))
                if run.spec.strip() != Path(spec_path).read_text().strip():
                    run = None  # spec changed: fork again
                    run_file.unlink()
                    answers_file.unlink(missing_ok=True)
            if run is None:
                run = await client.fork(Path(spec_path).read_text(), n_samples=a.n)
                run_file.write_text(run.model_dump_json(indent=1))
            if answers_file.exists() and run.status != "resolved":
                answers, other = load_answers(str(answers_file))
                run = await client.resolve(run, answers, other)
                run_file.write_text(run.model_dump_json(indent=1))
            if run.status == "resolved" and run.resolution and run.signature:
                write_outputs(client, run, a.out, a.module, None)
                comment.append(f"### SpecFork: `{name}` resolved. Locked {len(run.resolution.locked_cases)} test case(s) "
                               f"in `{a.out}/test_{run.signature.name}.py`.\n")
            else:
                open_count += len(run.open_questions)
                comment.append(questions_markdown(run, name))
    body = "\n".join(comment) or "SpecFork: no spec files matched."
    if a.comment_file:
        Path(a.comment_file).write_text(body)
    else:
        _p(body)
    return 1 if (a.fail_on_open and open_count) else 0


def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("specfork.server.main:create_app", factory=True, host=a.host, port=a.port)
    return 0


def cmd_mcp(a: argparse.Namespace) -> int:
    from .mcp_server import main as mcp_main

    mcp_main()
    return 0


def _n_range(v: str) -> int:
    n = int(v)
    if not 4 <= n <= 40:
        raise argparse.ArgumentTypeError("must be between 4 and 40")
    return n


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="specfork", description="Find the meanings hiding in a function spec.")
    ap.add_argument("--version", action="version", version=f"specfork {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--answers", help="JSON file: {question_id: option_id | {\"other\": text}}")
        p.add_argument("--auto", action="store_true", help="answer every question with the most common compatible behaviour")
        p.add_argument("--module", default="solution", help="module the generated tests import from (default: solution)")
        p.add_argument("--out", help="directory to write test_<fn>.py into")
        p.add_argument("--reference", help="file to write the reference implementation to")
        p.add_argument("--refork", action="store_true", help="re-fork the clarified spec and report agreement")
        p.add_argument("--decision-file", help="write the decision record (.specfork.yaml, or .json)")
        p.add_argument("--json", action="store_true", help="machine-readable output on stdout")
        p.add_argument("--allow-weak-sandbox", action="store_true",
                       help="run model-written code even without network isolation")

    f = sub.add_parser("fork", help="fork a spec into implementations and ask about the disagreements")
    f.add_argument("spec", help="the spec text, or - to read stdin")
    f.add_argument("-n", type=_n_range, default=24, help="number of implementations (4-40)")
    f.add_argument("--fast", help="model profile for framing/fan-out (default from settings)")
    f.add_argument("--deep", help="model profile for explanations (default from settings)")
    f.add_argument("--no-assumptions", action="store_true", help="skip the silent-assumption review")
    f.add_argument("--exception-types", action="store_true",
                   help="treat ValueError vs TypeError etc. as different behaviours and lock the type in tests")
    common(f)
    f.set_defaults(func=cmd_fork, is_async=True)

    r = sub.add_parser("resolve", help="answer the questions of a run saved with `fork --json`")
    r.add_argument("run", help="run JSON file")
    common(r)
    r.set_defaults(func=cmd_resolve, is_async=True)

    d = sub.add_parser("doctor", help="check model profiles (reachability, JSON, seed, reasoning, price) and the sandbox")
    d.add_argument("--all", action="store_true", help="check every profile that has an API key")
    d.set_defaults(func=cmd_doctor, is_async=True)

    s = sub.add_parser("serve", help="run the web UI and HTTP API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_serve, is_async=False)

    c = sub.add_parser("ci", help="repository ambiguity check: fork spec files, resolve committed answers, report questions")
    c.add_argument("specs", nargs="+", help="spec file globs, e.g. 'specs/*.md'")
    c.add_argument("-n", type=int, default=16)
    c.add_argument("--state", default=".specfork", help="directory for saved runs and answers files")
    c.add_argument("--out", default="tests/specfork", help="directory for locked test files")
    c.add_argument("--module", default="solution")
    c.add_argument("--comment-file", help="write the Markdown report here (for a PR comment)")
    c.add_argument("--fail-on-open", action="store_true", help="exit 1 while questions are unanswered")
    c.add_argument("--allow-weak-sandbox", action="store_true")
    c.set_defaults(func=cmd_ci, is_async=True)

    m = sub.add_parser("mcp", help="run the MCP server on stdio (for coding agents)")
    m.set_defaults(func=cmd_mcp, is_async=False)
    return ap


def main(argv: list[str] | None = None) -> int:
    from .pipeline import PipelineError

    a = build_parser().parse_args(argv)
    try:
        if a.is_async:
            return asyncio.run(a.func(a))
        return a.func(a)
    except (PipelineError, ForkError) as e:
        _p(f"error: {e}", err=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
