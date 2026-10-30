# Contributing to SpecFork

Thanks for your interest in SpecFork. This guide covers the development setup, the checks a change must
pass, the design principles the codebase follows, and how releases are made.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security vulnerabilities
must be reported privately, see [SECURITY.md](SECURITY.md), never in a public issue or pull request.

## Development setup

Requirements:

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 and the virtual environment for you; Python >= 3.11 is supported)
- Node.js 22 and npm (frontend)
- Docker (optional, to build the production image)
- Linux for the full sandbox test suite (network namespaces and rlimits); macOS works for most development

```bash
git clone https://github.com/maestrosatyam/SpecFork.git && cd SpecFork
cp .env.example .env     # only needed for live model calls (NEBIUS_API_KEY, ...)
make setup               # uv sync --extra dev  +  cd web && npm ci
```

`make setup` is equivalent to:

```bash
uv sync --extra dev      # creates .venv from pyproject.toml + uv.lock
cd web && npm ci
```

Run `make help` to list all targets. The most common ones:

| Command | What it does |
|---|---|
| `make dev` | API with auto-reload on http://localhost:8000 (`uv run uvicorn --factory specfork.server.main:create_app --reload --port 8000`) |
| `make web` | Vite dev server with hot reload (proxies `/api` to `make dev`) |
| `make build` | Production frontend build into `web/dist` (served by the API) |
| `make test` | Backend (pytest) and frontend (vitest) tests, fully offline |
| `make lint` | `uv run ruff check .` |
| `make typecheck` | `cd web && npm run typecheck` |
| `make probe` | `uv run specfork doctor`: checks configuration and makes a live call to the configured provider |
| `make eval` | Live benchmark evaluation (needs an API key; costs real money, a few cents) |
| `make mcp` | Run the MCP server (`uv run specfork mcp`) |
| `make docker-build` | `docker build -t specfork .` |

A fully simulated UI flow is available at `/?mock=1` (no inference, no key).

### Pre-commit hooks (optional)

```bash
uvx pre-commit install
```

The hooks run ruff and a few hygiene checks (trailing whitespace, YAML syntax, private-key detection).
The ruff `rev` in `.pre-commit-config.yaml` should match the ruff version locked in `uv.lock`; bump both together.

## Tests and lint

All tests are **offline**: model calls go through the scripted fake LLM in `tests/fake_llm.py`, so no API
key or network is needed, and CI never receives secrets.

```bash
uv run ruff check .          # lint
uv run pytest -q             # backend tests
uv run pytest -q tests/test_sandbox.py   # sandbox tests only
cd web && npm run typecheck && npm test  # frontend
uv run python evals/benchmark/validate.py   # benchmark integrity (offline)
```

CI (`.github/workflows/ci.yml`) runs ruff, pytest, the frontend typecheck/tests/build and a Docker build on
every push and pull request. A weekly job (`eval-smoke.yml`) validates the benchmark and the eval harness.

## Architecture

Start with [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). In short:

| Path | Contents |
|---|---|
| `specfork/` | Core library: pipeline orchestration, model client, sandbox and execution harness, behaviour clustering, canonicalisation, presets, provider profiles |
| `specfork/server/` | FastAPI app factory (`specfork.server.main:create_app`): HTTP API, SSE streaming, rate limits, spend cap |
| `specfork/cli.py` | `specfork` console script (`doctor`, `mcp`, ...) |
| `specfork/mcp_server.py` | MCP server exposing SpecFork to coding agents |
| `web/` | React + TypeScript + Tailwind frontend |
| `tests/` | Offline unit and integration tests |
| `evals/` | Benchmark (hand-written specs with hidden references) and the live eval runner |
| `docs/` | Architecture, API contract, evaluation results, security design |

Related docs: [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md), [`docs/EVALUATION.md`](docs/EVALUATION.md),
[`docs/SECURITY.md`](docs/SECURITY.md).

## Design principle: code decides, the model explains

SpecFork's value comes from *executed* evidence. Every decision that determines an outcome is made by
deterministic code over executed outputs:

- whether an implementation is valid (static checks, sandboxed execution),
- which implementations behave the same (clustering on canonical outputs),
- which inputs separate behaviours (witness selection),
- which behaviour survives the user's answers, and which tests are locked.

Models *propose* (signatures, probe inputs, candidate implementations) and *explain* (questions,
cluster summaries, the clarified spec prose). They never decide. When contributing:

- Do not replace a deterministic step with a model call. If a model output feeds a decision, validate it in
  code first and keep a deterministic fallback.
- Ground model prompts in executed outputs (witness inputs and real return values), not in the model's
  guesses about what code would do.
- Generated tests must come from executed behaviour, never from model-written assertions.
- Keep the pipeline testable offline: extend `tests/fake_llm.py` rather than requiring a live model.

## Adding a model provider profile

Providers are configured declaratively in `specfork/models.toml`; any OpenAI-compatible chat completions
endpoint can be added without code changes in most cases.

1. Add a profile to `specfork/models.toml`, following the existing entries: the base URL, the name of the
   environment variable holding the API key (never the key itself), the model IDs for each role (framing /
   fan-out / re-fork vs. explanation), any provider-specific request options (for example reasoning toggles),
   and per-token pricing so the spend cap and the cost shown in the UI stay accurate.
2. Document the new environment variable in `.env.example`.
3. If the provider needs behaviour that cannot be expressed in the profile (a different response shape,
   a different way to switch reasoning on or off), keep the adaptation small and inside the model client,
   and cover it with a test that uses a fake transport (see `tests/test_llm.py`).
4. Run `uv run specfork doctor` with the provider selected to confirm the live integration, and mention the
   result in your pull request. CI will not call the provider.

## Adding a preset

Presets are the one-click example specs in the UI (`specfork/presets.py`).

- Write a plain, realistic ticket of one paragraph. Do **not** hint at the ambiguity; the point is that
  SpecFork finds it.
- Prefer specs whose ambiguity shows up in executed outputs (rounding, empty input, ties, boundaries,
  time zones) rather than in style.
- Keep it within the sandbox's allow-listed standard library.
- Check it end to end with a live run before proposing it, and make sure `uv run pytest -q` passes
  (`tests/test_api.py` exercises the presets endpoint).

If you want a spec added to the **benchmark** instead, add it to `evals/benchmark/` with a hidden
reference, alternative references for each interpretation, and test inputs that distinguish them, then run
`uv run python evals/benchmark/validate.py`.

## Sandbox and security-sensitive changes

SpecFork executes model-written code derived from anonymous user input. Treat all generated code as
hostile. The design and the executed checks behind it are documented in
[`docs/SECURITY.md`](docs/SECURITY.md).

Changes to the sandbox, the execution harness, the static allow-list, environment handling, rate limits,
the spend cap, or HTTP security headers are security-sensitive. They must:

- include **regression tests in `tests/test_sandbox.py`** (or the relevant test module for non-sandbox
  controls) that demonstrate the attack is blocked and that legitimate code still works;
- never widen the allow-list (new modules, builtins or attributes) without a written justification in the
  pull request and a test showing the addition cannot be used to reach `os`, `sys`, frames, or the file system;
- update the corresponding table in `docs/SECURITY.md`;
- keep failure modes closed: if an isolation layer is unavailable in a deployed environment, refuse to run
  rather than run with less isolation.

If you discover a way to bypass the sandbox, report it privately first (see [SECURITY.md](SECURITY.md)).

## Commits and pull requests

- Branch from `main` and keep pull requests focused on one change.
- Write commit subjects in the imperative mood, under about 72 characters (for example
  `Sandbox: reject attrgetter gadget`). Explain the *why* in the body when it is not obvious.
- Fill in the pull request template, link the issue it addresses, and add a line under `## [Unreleased]` in
  [CHANGELOG.md](CHANGELOG.md) for user-visible changes.
- CI must be green. Reviews focus on correctness, tests, and keeping decisions in code.
- Sign-off is optional. If you like, certify the [Developer Certificate of Origin](https://developercertificate.org/)
  by committing with `git commit -s`, which adds a `Signed-off-by:` line.
- By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).

## Release process

SpecFork uses [Semantic Versioning](https://semver.org/) and keeps a human-written
[CHANGELOG.md](CHANGELOG.md) in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.

1. Make sure `main` is green in CI.
2. Move the entries under `## [Unreleased]` into a new `## [X.Y.Z] - YYYY-MM-DD` section and update the
   comparison links at the bottom of the changelog.
3. Bump the version in `pyproject.toml` (and `web/package.json`), then run `uv lock`.
4. Commit (`Release vX.Y.Z`), tag with an annotated tag `git tag -a vX.Y.Z -m "vX.Y.Z"`, and push the tag.
5. Create a GitHub release from the tag, using the changelog section as the release notes.

Before 1.0.0, minor versions may contain breaking changes; they are called out in the changelog.

## Maintainer

SpecFork is maintained by Satyam Dwivedi ([@maestrosatyam](https://github.com/maestrosatyam)).
