# Changelog

All notable changes to SpecFork are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Open questions** (opt-in, `SPECFORK_OPEN_QUESTIONS=1`): after the witness-backed questions, up to three
  free-text questions about what the executed evidence did not cover. Free-text answers are implemented and
  executed, then become the reference. Web UI section "Anything else? (optional)".
- **Exception types as behaviours** (`--exception-types`), **adaptive N** (`SPECFORK_ADAPTIVE_N`), a **second
  probing round** (`SPECFORK_PROBE_ROUNDS=2`), a **YAML decision record** (`--decision-file .specfork.yaml`,
  `/export.yaml`), **mixed-model fan-out** (`SPECFORK_IMPLEMENTERS`) and an optional Qwen3 implementer profile.
- Evaluation: `--repeats`, bootstrap confidence intervals, and a scheduled benchmark workflow.

### Changed

- The evaluation report now pools five runs with default settings, including a re-run of the original code.
  SpecFork scores 33.1% against 45.7% for an ask-first baseline. The earlier single-run "tie" did not
  reproduce. See `docs/EVALUATION.md`.
- Free-text answers get up to four implementation attempts across both models.

## [0.2.0] - 2026-10-30

SpecFork becomes an installable tool: the same engine now runs from the terminal, from coding agents (MCP),
from CI, from Python and from the web UI, with any model provider.

### Added

- **Python package `specfork`** with a library API (`from specfork import Client`: `fork`, `resolve`,
  `converge`, `tests`) and typed run models (`Run`, `Question`, …). Importing the package has no side
  effects. Installable from GitHub with the `server` and `mcp` extras (PyPI publication pending).
- **CLI** (`specfork fork`, `resolve`, `doctor`, `serve`, `mcp`): interactive or `--json` output,
  `--answers` files, `--auto` answers for CI, `--module` and `--out` for the generated pytest file,
  `--reference`, `--refork`, and `--allow-weak-sandbox`.
- **MCP server** (`specfork mcp`, stdio) with the tools `fork_spec`, `list_questions`, `answer`,
  `get_tests`, `get_clarified_spec` and `refork`; instructs agents to relay questions to the user.
- **Provider registry**: model profiles as data in `specfork/models.toml` plus a user `specfork.toml`
  (base URL, key variable, reasoning mode, seed and JSON support, price, roles), with adapters for
  OpenAI-compatible endpoints, Anthropic and Gemini. The Anthropic and Gemini adapters are unit-tested
  against recorded request/response shapes, not yet verified live.
- **`specfork doctor`**: checks the sandbox isolation and each model profile (reachability, JSON output,
  seed, reasoning toggle, price).
- **Settings object** (`specfork.config.Settings`): all configuration in one place, read once from the
  environment and `.env`; `SPECFORK_FAST_MODEL`, `SPECFORK_DEEP_MODEL`, `SPECFORK_IMPLEMENTERS`,
  `SPECFORK_MODELS_FILE`, `SPECFORK_PUBLIC_DEMO`, `SPECFORK_ASSUMPTIONS`, `SPECFORK_DB` and more.
- **Free-text answers** ("Other…"): describe a behaviour no sampled implementation produced; the deep
  model implements it, it is executed in the sandbox, and its outputs are locked like any other option.
- **Mixed-model fan-out**: `SPECFORK_IMPLEMENTERS` assigns implementations round-robin across several
  profiles, for the fan-out and the re-fork.
- **Capability tokens**: creating a run returns a token; answering and re-forking require it
  (`X-Run-Token`). Only a SHA-256 digest is stored.
- **SQLite run store** (`SPECFORK_DB`): runs and token digests survive restarts; memory-only in
  public-demo mode.
- **Public-demo mode** (`SPECFORK_PUBLIC_DEMO=1`): no API docs, priced models only, memory-only store,
  non-dumpable server process.
- **OpenAPI schema** at `/openapi.json` and `/docs` outside public-demo mode.
- **JSON decision record** export (`GET /api/runs/{id}/export.json`): spec, clarified spec, signature,
  decisions, locked cases, agreement, models, prompt version and hash.
- **Test module option**: `tests.py?module=pkg.mod`, `--module` and `get_tests(module=…)` generate tests
  that import the function from your module.
- **Model choice in the API**: `fast_model`, `deep_model` and `assumptions` on `POST /api/runs`, limited
  to allow-listed profiles.
- **Docs**: architecture, providers, CLI and MCP reference; refreshed README and security design.
- **Community files and CI**: GitHub Actions CI (ruff, offline pytest, frontend typecheck/tests/build,
  Docker build), a weekly offline eval smoke job, Dependabot, issue and pull request templates,
  `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, pre-commit hooks.

### Changed

- **Calibrated silent-assumption review**: assumption questions are kept only above a confidence
  threshold (0.6), at most two per run, and only when backed by an executed probe; the review can be
  switched off per run (`assumptions`, `--no-assumptions`, `SPECFORK_ASSUMPTIONS`).
- The backend moved from `app/` to the `specfork` package (`specfork.server.main:create_app` for the HTTP
  server); dependencies are declared in `pyproject.toml` and locked with `uv.lock`
  (`requirements*.txt` removed).
- Run ownership moved from the client address to capability tokens.
- **Frontend**: human-readable option labels, a sandbox isolation badge, model labels from the server,
  and a smaller initial bundle (vendor chunk split, lazily loaded highlighter and drawers).
- Each run records a hash of the prompts next to the prompt version.
- The codebase is ruff lint-clean.

### Security

- The CLI refuses to execute model-written code without network isolation unless `--allow-weak-sandbox`
  is passed; the MCP server requires `SPECFORK_ALLOW_WEAK_SANDBOX=1` for the same.
- Public-demo mode refuses unpriced model profiles, so the daily budget cap cannot be disabled by
  configuration.

## [0.1.0] - 2026-10-30

Initial public release.

### Added

- **Web app**: React + TypeScript + Tailwind UI served by a FastAPI backend, with live progress over
  server-sent events, one-click example presets, an "Under the hood" panel showing every model call
  (model ID, latency, tokens, cost, reasoning excerpt), and a clearly labelled offline mock mode (`/?mock=1`).
- **Pipeline**: frame a typed signature and edge-case probe inputs (plus deterministic type-driven fuzz
  inputs), fan out N independent implementations, execute them all, cluster by canonical executed
  outputs, choose witness inputs by greedy pair separation, and turn each disagreement into a
  plain-English clarifying question. Silent-assumption review of the consensus behaviour.
- **Resolution**: user answers select the surviving, mutually compatible behaviour; a pytest file is
  generated deterministically from executed outputs on decided and consensus cases; a clarified spec and
  a reference implementation are produced; a final re-fork measures agreement before and after.
- **Model integration**: OpenAI-compatible client for Nebius Token Factory with NVIDIA Nemotron 3.5
  Lightning (framing, fan-out, re-fork) and Nemotron 3 Ultra (explanations, clarified spec), with
  metered token cost and a reasoning fallback.
- **Sandbox**: AST allow-list of standard-library modules, proxied modules and restricted builtins,
  known escape-gadget rejection, `python -I -S` subprocess with a stripped environment, rlimits (CPU,
  memory, file size, file descriptors, processes), per-call timeouts with process-group kill, bounded
  output, a fresh network namespace, a non-dumpable server process and a non-root container user.
  Deployed instances fail closed when network isolation is unavailable.
- **Abuse controls**: per-visitor sliding-window rate limit, a global daily USD spend cap reserved at
  admission, private run listing, owner-only answers, SSE caps, CSP and security headers, and no public
  API docs endpoints.
- **Benchmark**: 32 hand-written specs (26 ambiguous, 6 clear) with hidden reference implementations,
  alternative references per interpretation and distinguishing test inputs, plus an offline validator
  (`evals/benchmark/validate.py`).
- **Evaluation**: live eval runner comparing no clarification, an ask-first baseline and SpecFork on
  intent alignment; results and failure cases in `docs/EVALUATION.md`.
- **Tests**: offline backend test suite using a scripted fake LLM (pipeline, API, model client,
  sandbox, eval harness) and frontend tests with Vitest.
- **Deployment**: multi-stage Dockerfile (Node 22 frontend build, Python 3.12 runtime) and a Cloud Run
  deploy script.
- Documentation: README, API contract, evaluation report and security design (`docs/SECURITY.md`).

[Unreleased]: https://github.com/maestrosatyam/SpecFork/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/maestrosatyam/SpecFork/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/maestrosatyam/SpecFork/releases/tag/v0.1.0
