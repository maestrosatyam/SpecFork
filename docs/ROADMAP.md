# Roadmap

Status of the 20 issues from the open-source readiness review (2026-10-30), as of v0.2.0.
"Done" means implemented with tests in this repository. "Partial" and "Deferred" say exactly what is missing.

| # | Issue | Status | What shipped / what is left |
|---|---|---|---|
| 1 | Community health and CI | **Done** | CI (ruff, basedpyright, pytest, OpenAPI drift, vitest, typecheck, build, Docker), Dependabot, issue/PR templates, CONTRIBUTING, Code of Conduct, root SECURITY.md, CHANGELOG, pinned dev tools in `uv.lock`, pre-commit, Makefile `help`. Left: push tags `v0.1.0`/`v0.2.0` with the first public release. |
| 2 | Fix doc drift | **Done** | `docs/API_CONTRACT.md` now points at the generated `docs/openapi.json` (CI fails on drift); SECURITY.md limits checked by a test; UI model names come from `/api/health`; stale comments removed. |
| 3 | One settings object | **Done** | `specfork.config.Settings`; importing `specfork` reads or changes nothing in `os.environ`; one `.env` loader. |
| 4 | Provider registry and capability profiles | **Done (verified live on Nebius only)** | `models.toml` + user `specfork.toml`; `chat_template_kwargs` only for profiles that declare it; public mode refuses unpriced models; per-run model choice from an allow-list. Plain OpenAI-compatible request shape is unit-tested; not yet run against a live Ollama/vLLM/OpenAI endpoint. |
| 5 | `specfork` core library | **Done** | `from specfork import Client` (no FastAPI needed); typed Pydantic `Run`; server, CLI, MCP and eval use the library; basedpyright (standard mode) passes on the core. |
| 6 | Package and CLI | **Done, publication pending** | `specfork fork/resolve/doctor/serve/mcp/ci`, `--json`, `--module`, wheel with bundled UI (`make package`). Left: publish to PyPI (needs the maintainer's PyPI account). |
| 7 | MCP server | **Done, listing pending** | 6 tools; verified with the official Python MCP client (live fork → answer → tests) and a raw JSON-RPC client; automated test. Left: registry listing; test in Claude Desktop/Cursor. |
| 8 | GitHub Action | **Partial (experimental)** | `action.yml` wraps `specfork ci` (fork specs, comment questions with witnesses, resolve committed answers, write locked tests, optional failing gate). `specfork ci` is tested offline; the action itself has not yet run on GitHub. Left: opening a PR with the tests automatically. |
| 9 | Free-text "Other…" answers | **Done (no eval gain yet)** | The deep model implements the free text; it is executed and becomes an evidence-backed option and the reference. In the benchmark the simulated owner never chose free text, so the three named items did not improve. Left: an eval condition that forces free text when no option matches. |
| 10 | Calibrate the assumption review | **Partial: trade-off measured, targets not met** | Confidence, cap and witness requirement are configurable. Strict settings cut false alarms on clear specs (2.0 → 0.83 per spec) but lowered ambiguous-spec alignment (to 21.8%); defaults stay recall-oriented. See docs/EVALUATION.md. |
| 11 | Persistent store and run tokens | **Done (SQLite); Postgres deferred** | Per-run capability tokens replace IP ownership; SQLite store survives restarts and is shared by processes on one host. Left: Postgres backend and resumable stage jobs for multi-host scale-out. |
| 12 | Visible sandbox strength | **Done** | UI badge, server startup warning, CLI refuses weak isolation without `--allow-weak-sandbox`, MCP needs `SPECFORK_ALLOW_WEAK_SANDBOX=1`. |
| 13 | Anthropic and Gemini adapters, `doctor` | **Done (adapters not verified live)** | Native adapters with reasoning mapping (unit-tested against recorded request/response shapes), per-profile prompt overrides, `specfork doctor` (reachability, JSON, seed, reasoning, price). |
| 14 | OpenAPI and generated client types | **Partial** | OpenAPI served outside public-demo mode, committed `docs/openapi.json` with a CI drift check. Left: generate `web/src/types.ts` from it. |
| 15 | Mixed-model fan-out | **Partial** | `SPECFORK_IMPLEMENTERS` assigns implementations round-robin across profiles; per-model cluster shares in the UI. Left: the "SF-mixed" eval condition. |
| 16 | Adaptive probing and exception types | **Partial** | Exception types as behaviours and locked in tests (`--exception-types`). Left: a second probing round targeting near-identical clusters; Hypothesis strategies from signature types. |
| 17 | Benchmark with confidence intervals | **Partial** | Bootstrap 95% intervals in every eval table; scheduled benchmark workflow (needs the `NEBIUS_API_KEY` repository secret). Left: multiple seeds per run and publishing results to the docs site. |
| 18 | TypeScript target language | **Deferred** | Needs a language-plugin interface and an isolated JS runtime; large. |
| 19 | Pluggable sandbox backends | **Deferred** | Interface plus Docker/gVisor backend, with the security suite run against each backend. |
| 20 | Docs site, exports, polish | **Partial** | MkDocs site + Pages workflow, JSON decision-record export, main bundle 125 kB (was 579 kB). Left: `.specfork.yaml` export, adaptive N, recipe gallery. |
