# SpecFork

[![CI](https://github.com/maestrosatyam/SpecFork/actions/workflows/ci.yml/badge.svg)](https://github.com/maestrosatyam/SpecFork/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**SpecFork is the ambiguity linter for specs: run it before your coding agent writes code — from your
terminal, your agent (MCP), your CI, or the web UI — with any model.**

A one-paragraph function spec usually means more than one thing. SpecFork has a model write many
independent implementations, *runs* them all in a sandbox, and groups them by what they actually do. Each
place they disagree becomes a question backed by a real input and the real outputs. Your answers become a
clarified spec, a pytest file locked from executed behaviour, and a reference implementation. An optional
re-fork measures how many fresh implementations now agree with what you meant.

By default SpecFork runs **NVIDIA Nemotron 3.5 Lightning** and **NVIDIA Nemotron 3 Ultra** on
**Nebius Token Factory**. Any OpenAI-compatible endpoint, Anthropic or Gemini can be configured instead.

**Live demo: <https://specfork-ybzssouqyq-uc.a.run.app>** (NVIDIA Nemotron on Nebius Token Factory; no
login; 6 live runs per 10 minutes per visitor) · License: MIT

## What it does

```
$ specfork fork "Split a restaurant bill evenly among n people and return the list of amounts each person pays, rounded to cents."

def split_bill(total: float, n: int, tip_percent: float) -> list[float]
24 implementations ran on 20 probes → 10 distinct behaviour(s)
  ...

Question 1: If the caller provides a non-positive number of people, should the function raise an error,
            return an empty list, or something else?
  [1] Returns an empty list  (16 impl)
        split_bill(total=100.0, n=-1, tip_percent=0.0) -> []
  [2] Raises ValueError  (7 impl)
        split_bill(total=100.0, n=-1, tip_percent=0.0) -> raises
  [3] Returns a list with a single zero  (1 impl)
  [o] Other… (describe the behaviour you want)

Silent assumption 2: Should the amounts add up exactly to the total, or may the rounded shares leave
                     a few cents unaccounted for?
  [1] Round each share independently; accept a small total mismatch.  (14 impl)
        split_bill(total=100.0, n=3, tip_percent=0.0) -> [33.33, 33.33, 33.33]
  [2] Distribute rounding remainder so the summed payments equal the exact total.  (proposed, not executed)
  [o] Other… (describe the behaviour you want)
```

The output above is abridged from the recorded sample run
[`specfork/samples/split_bill.json`](specfork/samples/split_bill.json). In that run, 4 of 24 original
implementations matched the chosen behaviour on the locked cases (17%); after clarification, 17 of 22
fresh implementations did (77%).

You get back:

- a **clarified spec** that states only the points you decided;
- a **pytest file** whose expected values come from executed outputs, never from model-written assertions;
- a **reference implementation** (the chosen behaviour, or a new executed implementation of your free-text answer);
- a **decision record** (JSON) you can commit next to the code.

## Quickstart

Requires Python 3.11+, an API key for a model provider (`NEBIUS_API_KEY` for the defaults) and, for full
sandbox isolation, Linux or Docker. SpecFork is not on PyPI yet (publication is pending); install it from
GitHub:

```bash
export NEBIUS_API_KEY=...        # or put it in ./.env

# run once without installing (uv)
uvx --from git+https://github.com/maestrosatyam/SpecFork specfork fork "Truncate a string to at most max_len characters, adding '...' at the end if it was shortened."

# or install into an environment (pip; pipx works the same way), with the web server and MCP extras
pip install "specfork[server,mcp] @ git+https://github.com/maestrosatyam/SpecFork"
specfork doctor                  # check models, keys, prices and sandbox isolation
```

## CLI

```bash
specfork fork "<spec>"                                   # interactive: answer each question in the terminal
specfork fork - < spec.txt                               # read the spec from stdin
specfork fork --json "<spec>" > run.json                 # the run (with its questions) as JSON, no prompts
specfork resolve run.json --answers answers.json \
    --module billing.split --out tests/                  # answer later; writes tests/test_split_bill.py
specfork fork "<spec>" --auto --refork --out tests/      # CI: most common compatible behaviour, then re-fork
specfork doctor [--all]                                  # check model profiles and the sandbox
specfork serve [--host 127.0.0.1] [--port 8000]          # web UI + HTTP API
specfork mcp                                             # MCP server on stdio
```

| Option | Meaning |
|---|---|
| `--json` | machine-readable run on stdout |
| `--answers FILE` | answers JSON: `{"q0": "q0g1", "a0": {"other": "raise ValueError for negative totals"}}` |
| `--auto` | answer every question with the most common compatible behaviour (useful in CI) |
| `--module NAME` | module the generated tests import the function from (default `solution`) |
| `--out DIR` | write `test_<function>.py` into `DIR` |
| `--reference FILE` | write the reference implementation to `FILE` |
| `--refork` | re-implement the clarified spec and report agreement before and after |
| `--allow-weak-sandbox` | run model-written code even when the host cannot isolate the network |
| `-n`, `--fast`, `--deep`, `--no-assumptions` | (`fork` only) number of implementations, model profiles, skip the silent-assumption review |

The CLI refuses to execute model-written code when the sandbox cannot drop network access (macOS, Windows,
or Linux with unprivileged user namespaces disabled) unless you pass `--allow-weak-sandbox`. Full reference:
[`docs/CLI_AND_MCP.md`](docs/CLI_AND_MCP.md).

## MCP (for coding agents)

`specfork mcp` exposes `fork_spec`, `list_questions`, `answer`, `get_tests`, `get_clarified_spec` and
`refork` over stdio. The server instructs the agent to relay every question to you instead of answering on
your behalf.

```json
{
  "mcpServers": {
    "specfork": {
      "command": "uvx",
      "args": ["--from", "specfork[mcp] @ git+https://github.com/maestrosatyam/SpecFork", "specfork", "mcp"],
      "env": { "NEBIUS_API_KEY": "..." }
    }
  }
}
```

## Python API

```python
import asyncio
from specfork import Client

async def main():
    async with Client() as sf:                      # settings from the environment / .env
        run = await sf.fork("Split a bill evenly among n people, rounded to cents.")
        for q in run.open_questions:
            print(q.text, [o.label for o in q.options])
        run = await sf.resolve(run, {q.id: q.options[0].id for q in run.open_questions})
        print(run.resolution.clarified_spec)
        print(sf.tests(run, module="billing"))

asyncio.run(main())
```

`Client.resolve(run, answers, other)` also takes free-text answers (`{question_id: text}`), and
`Client.converge(run)` runs the re-fork. Importing `specfork` has no side effects.

## Web UI

```bash
git clone https://github.com/maestrosatyam/SpecFork.git && cd SpecFork
cp .env.example .env                       # add NEBIUS_API_KEY
make setup && make build                   # uv + npm; builds web/dist
uv run specfork serve                      # http://127.0.0.1:8000

# or with Docker (SPECFORK_DB= keeps runs in memory; the image's working directory is read-only)
docker build -t specfork . && docker run --rm -p 8080:8080 -e NEBIUS_API_KEY -e SPECFORK_DB= specfork
```

The web UI shows live progress, the executed examples behind every option, an **Under the hood** panel with
every model call (model, latency, tokens, cost, reasoning excerpt), the sandbox isolation status, and
exports (pytest file with a chosen module path, Markdown, JSON decision record). The frontend is built from
a source checkout (or the Docker image); a `pip` install serves the HTTP API only. A fully simulated flow is
available at `/?mock=1` (clearly labelled; no inference). The HTTP API is described in
[`docs/API_CONTRACT.md`](docs/API_CONTRACT.md); outside public-demo mode the OpenAPI schema is served at
`/openapi.json` and `/docs`.

## Models and providers

| Role | Default profile | Model (Nebius Token Factory ID) | Reasoning |
|---|---|---|---|
| fast: framing, fan-out, re-fork | `lightning`: **NVIDIA Nemotron 3.5 Lightning** | `nvidia/Nemotron-3_5-Lightning` | off |
| deep: explanations, silent assumptions, clarified spec | `ultra`: **NVIDIA Nemotron 3 Ultra** | `nvidia/Nemotron-3-Ultra-550b-a55b` | on, medium effort (falls back to off) |

Both are served by **Nebius Token Factory** (`https://api.tokenfactory.nebius.com/v1`, OpenAI-compatible).
Model profiles are data, not code: add a `specfork.toml` to use NVIDIA NIM, vLLM, Ollama, OpenRouter, any
other OpenAI-compatible endpoint, Anthropic or Gemini, then select profiles with `SPECFORK_FAST_MODEL`,
`SPECFORK_DEEP_MODEL` and `SPECFORK_IMPLEMENTERS` (several profiles for a mixed-model fan-out). See
[`docs/PROVIDERS.md`](docs/PROVIDERS.md); `specfork doctor` checks every profile in use.

## How it works

**Code decides, the model explains.** Models propose signatures, probe inputs and implementations, and
write the prose. Which implementations behave alike, which inputs separate them, which behaviour survives
your answers and which tests are locked are all decided by deterministic code over executed outputs.

| Stage | What happens | Who decides |
|---|---|---|
| 1. Frame | the fast model proposes a typed signature and edge-case probe inputs; deterministic type-driven fuzz inputs are added | model proposes, code validates |
| 2. Fan-out | N independent implementations (default 24; temperature 1.0, distinct seeds; one model or several) | model |
| 3. Execute | each implementation passes an AST allow-list, then runs on every probe in an isolated subprocess | **code** |
| 4. Cluster | identical canonical outputs on all probes form one *behaviour*; witness inputs are chosen by greedy pair separation | **code** |
| 5. Explain + silent assumptions | the deep model turns each split into a question and flags likely bugs; it also reviews the majority behaviour for decisions every implementation made silently (kept only above a confidence threshold and when backed by an executed probe) | model, grounded in executed outputs |
| 6. Resolve | your answers (an option, or a free-text **Other…** answer) select the surviving compatible behaviour; a free-text answer is implemented and executed like every other option; tests are locked from executed outputs on decided and consensus cases; the deep model rewrites the spec with only the decided points | **code**, model for prose |
| 7. Re-fork | N fresh implementations of the clarified spec run against the locked tests: agreement before vs after | **code** |

Design details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Results (honest summary)

<!-- EVAL_SUMMARY -->
A live benchmark measures intent alignment: the share of fresh implementations that match a hidden reference.
It uses 26 ambiguous and 6 clear hand-written specs, with N=12 implementations per condition. The figures are
pooled over five runs with default settings, including a re-run of the original code.

| Condition (ambiguous specs) | Intent alignment |
|---|---|
| No clarification | 20.8% |
| One ask-first prompt + rewrite | 45.7% |
| SpecFork | 33.1% |

**SpecFork currently trails a well-prompted ask-first baseline on this metric.** An early single run that showed
a tie did not reproduce.
- **Where SpecFork wins clearly:** when the deciding behaviour only shows up once code runs (`page_count`,
  `cart_discounts`).
- **Where it loses:** when the owner's intent is something no sampled implementation did.
- **What only SpecFork produces:** an executed witness for every question, deterministic locked tests, and a
  measured re-fork.

Every run, the attempted fixes and their trade-offs: [`docs/EVALUATION.md`](docs/EVALUATION.md).

## Security

Model-written code is treated as hostile: an AST allow-list, proxied stdlib modules, restricted builtins,
a `python -I -S` subprocess with an empty environment, rlimits (CPU, 512 MB address space, no file writes,
32 file descriptors, no new processes), timeouts with process-group kill, bounded output, and a fresh
network namespace where the kernel allows it. The server adds per-run capability tokens, rate limits, a
daily spend cap and a public-demo mode. Design and tests: [`docs/SECURITY.md`](docs/SECURITY.md). To report
a vulnerability, follow [`SECURITY.md`](SECURITY.md).

## Project health

- CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)): ruff, the offline pytest suite (scripted fake
  model, no network, no secrets), frontend typecheck/tests/build, and a Docker build.
- [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) · [Changelog](CHANGELOG.md) ·
  [Code of Conduct](CODE_OF_CONDUCT.md)
- Docs: [Architecture](docs/ARCHITECTURE.md) · [Providers](docs/PROVIDERS.md) ·
  [CLI and MCP](docs/CLI_AND_MCP.md) · [HTTP API](docs/API_CONTRACT.md) · [Evaluation](docs/EVALUATION.md) ·
  [Security design](docs/SECURITY.md)

## Prior art and honesty

The core signal (sample many programs, execute, cluster, ask) is known from research: ClarifyGPT
(Mu et al., 2023), TiCoder (Lahiri et al., 2022), and AlphaCode's behavioural clustering. SpecFork's
contribution is the product loop around it: witness-backed questions, free-text answers that are executed
too, deterministic locked tests, a measured re-fork, and the same engine behind a CLI, an MCP server, a
Python library and a web UI.

Limits: SpecFork cannot surface an ambiguity that every sampled implementation resolves the same way (the
silent-assumption review covers this only partly), and on simple specs the assumption review can ask
questions that are not needed. It targets single Python functions that use the standard library.

## Built for the Nebius × NVIDIA Global AI Hackathon 2026

SpecFork was built for the Nebius × NVIDIA Global AI Hackathon 2026 (track: Coding and Agentic
Engineering), with NVIDIA Nemotron open models served by Nebius Token Factory.

## License

MIT, see [LICENSE](LICENSE). Maintained by Satyam Dwivedi ([@maestrosatyam](https://github.com/maestrosatyam)).
