# CLI and MCP reference

SpecFork installs one console script, `specfork`, with five commands. `specfork mcp` turns the same engine
into an MCP server for coding agents.

Install from GitHub (SpecFork is not on PyPI yet):

```bash
uvx --from git+https://github.com/maestrosatyam/SpecFork specfork --help
pip install "specfork[server,mcp] @ git+https://github.com/maestrosatyam/SpecFork"
```

`serve` needs the `server` extra and `mcp` needs the `mcp` extra. Settings come from the environment and
from `./.env` in the current directory; see the variable table in [`specfork/config.py`](../specfork/config.py)
and model selection in [PROVIDERS.md](PROVIDERS.md).

## Commands

```
specfork [--version] {fork,resolve,doctor,serve,mcp} ...
```

### `specfork fork`

Fork a spec into implementations, execute and cluster them, and ask about the disagreements.

```
specfork fork SPEC [-n N] [--fast PROFILE] [--deep PROFILE] [--no-assumptions]
                   [--answers FILE | --auto] [--module NAME] [--out DIR] [--reference FILE]
                   [--refork] [--json] [--allow-weak-sandbox]
```

| Argument | Default | Meaning |
|---|---|---|
| `SPEC` | – | the spec text, or `-` to read it from stdin |
| `-n N` | 24 | number of implementations (use 4–40; also used for `--refork`) |
| `--fast PROFILE` | `SPECFORK_FAST_MODEL` | profile key or model id for framing, fan-out and re-fork (overrides `SPECFORK_IMPLEMENTERS`) |
| `--deep PROFILE` | `SPECFORK_DEEP_MODEL` | profile key or model id for explanations, assumptions and the clarified spec |
| `--no-assumptions` | off | skip the silent-assumption review |
| *common options* | | see below |

Behaviour:

- Without `--json`: prints the signature, the behaviours, then asks each question interactively (option
  number, or `o` for a free-text answer of 3–300 characters), resolves, and prints the clarified spec, the
  number of locked cases and the agreement.
- `--json` alone: prints the unresolved run as JSON and exits; no questions are asked. Save it and answer
  later with `specfork resolve`.
- `--json` with `--answers` or `--auto`: resolves (and re-forks with `--refork`) and prints the resolved
  run as JSON.

Exit code 1 if the fork fails (for example, too few implementations could be executed).

### `specfork resolve`

Answer the questions of a run saved with `specfork fork --json`.

```
specfork resolve RUN.json [--answers FILE | --auto] [--module NAME] [--out DIR] [--reference FILE]
                          [--refork] [--json] [--allow-weak-sandbox]
```

Without `--answers` or `--auto` the questions are asked interactively. The run file is not modified; use
`--json` to get the resolved run on stdout.

### Common options (`fork` and `resolve`)

| Option | Meaning |
|---|---|
| `--answers FILE` | answers JSON (format below) |
| `--auto` | answer every question with the option chosen by the most implementations among those compatible with the earlier answers; proposed (unexecuted) alternatives are never picked, so silent assumptions are kept |
| `--module NAME` | dotted module path the generated tests import the function from (default `solution`) |
| `--out DIR` | write `DIR/test_<function>.py` (the directory is created) |
| `--reference FILE` | write the reference implementation to `FILE` |
| `--refork` | after resolving, re-implement the clarified spec N times and report agreement with the locked tests |
| `--json` | machine-readable output on stdout (also silences the weak-sandbox warning) |
| `--allow-weak-sandbox` | run model-written code even if the sandbox cannot drop network access |

### Weak sandbox isolation

Before executing any model-written code, the CLI runs a sandbox self-test. If the child process cannot
enter a fresh network namespace (macOS, Windows, containers without user namespaces, or Linux with
unprivileged user namespaces disabled), the CLI stops with an explanation unless you pass
`--allow-weak-sandbox`. All other sandbox layers (AST allow-list, restricted builtins, empty environment,
rlimits, timeouts) still apply. Running on Linux or in Docker gives full isolation. See
[SECURITY.md](SECURITY.md).

### `specfork doctor`

```
specfork doctor [--all]
```

Checks the sandbox (works? network isolation?) and each model profile in use (`--all`: every profile):
price present, reachable, JSON output, seed honoured, reasoning toggle. Exit code 1 if any profile is
unreachable or missing its key. Details in [PROVIDERS.md](PROVIDERS.md#specfork-doctor).

### `specfork serve`

```
specfork serve [--host 127.0.0.1] [--port 8000]
```

Runs the HTTP API (and the web UI, when `web/dist` has been built in a source checkout) with uvicorn. See
[ARCHITECTURE.md](ARCHITECTURE.md#http-api) for the endpoints and the README for Docker.

### `specfork mcp`

Runs the MCP server on stdio. See [MCP server](#mcp-server).

## `answers.json`

A JSON object mapping question ids to an option id, or to `{"other": "<free text>"}`:

```json
{
  "q0": "q0g1",
  "q5": "q5g0",
  "a0": {"other": "raise ValueError for negative totals"},
  "a1": "a1alt"
}
```

| Question kind | Id | Option ids |
|---|---|---|
| ambiguity (implementations disagree) | `q<k>` | `q<k>g<i>`, one per group of behaviours |
| likely bug | `q<k>` | answered automatically with the non-buggy option; you may override it |
| silent assumption | `a<k>` | `a<k>keep` (what the implementations did) or `a<k>alt` (the proposed alternative) |

Every ambiguity and assumption question must be answered, either with an option or with free text. A
free-text answer is something no sampled implementation did: the deep model implements the clarified spec,
the implementation is executed in the sandbox, and its outputs become the locked expectations for that
question. Get the ids from `specfork fork --json` (`questions[].id` and `questions[].options[].id`).

## Using SpecFork in CI

```bash
# fully automatic: lock the majority-compatible behaviour and measure the re-fork
specfork fork --auto --refork --json --module mypkg.billing --out tests/generated \
  "Split a restaurant bill evenly among n people and return the list of amounts each person pays, rounded to cents." \
  > specfork-run.json

# reviewed: fork once, commit answers.json after a human picks, resolve in CI
specfork fork --json "$(cat specs/split_bill.txt)" > run.json
specfork resolve run.json --answers answers.json --module mypkg.billing --out tests/generated
```

The model calls are not deterministic across providers and versions, so a re-run can produce different
questions; commit the resolved run (or the decision record) together with the generated tests. CI hosts
are usually Linux, where full sandbox isolation is available; GitHub-hosted Ubuntu runners may restrict
unprivileged user namespaces, in which case `specfork doctor` reports weak isolation.

## MCP server

`specfork mcp` serves six tools over stdio. Its instructions tell the agent to call `fork_spec` before
implementing a spec, relay every question (with its executed examples) to the user, let the user choose,
and then implement against `get_tests` and `get_clarified_spec`. Runs live in the memory of the MCP server
process.

| Tool | Arguments | Returns |
|---|---|---|
| `fork_spec` | `spec: str`, `n_samples: int = 16` (clamped to 4–40), `assumptions: bool = true` | `run_id`, `signature`, `behaviours` (label, implementations, summary), `questions`, `cost_usd`, `next_step`; or `error` |
| `list_questions` | `run_id: str` | `run_id`, `questions` |
| `answer` | `run_id: str`, `answers: {question_id: option_id}`, `other: {question_id: text}` (optional) | `clarified_spec`, `decisions`, `locked_cases` (count), `agreement_before`, `next_step`; or `error` |
| `get_tests` | `run_id: str`, `module: str = "solution"` | pytest file text |
| `get_clarified_spec` | `run_id: str` | clarified spec text |
| `refork` | `run_id: str`, `n_samples: int = 16` | `agreement_before`, `agreement_after` |

Each question in `fork_spec` / `list_questions` has `id`, `kind` (`ambiguity` or `assumption`), `question`,
`why`, `options` (each with `id`, `answer`, `implementations`, up to two `executed_examples` such as
`split_bill(total=100.0, n=-1, tip_percent=0.0) -> []`, and `proposed_example` for unexecuted
alternatives) and `free_text_allowed: true`.

### Weak isolation in MCP

`fork_spec` runs the sandbox self-test and returns an error when network isolation is unavailable, unless
the server's environment has `SPECFORK_ALLOW_WEAK_SANDBOX=1`. Set it only if you accept running
model-written code without a network namespace (for example on macOS).

### Client configuration

Claude Desktop, Claude Code (`.mcp.json`) and most other MCP clients use this JSON shape. Pass API keys and
settings through `env`; the server's working directory is chosen by the client, so do not rely on `.env`.

```json
{
  "mcpServers": {
    "specfork": {
      "command": "uvx",
      "args": ["--from", "specfork[mcp] @ git+https://github.com/maestrosatyam/SpecFork", "specfork", "mcp"],
      "env": {
        "NEBIUS_API_KEY": "...",
        "SPECFORK_ALLOW_WEAK_SANDBOX": "0"
      }
    }
  }
}
```

With SpecFork installed in an environment (`pip install "specfork[mcp] @ git+…"`):

```json
{
  "mcpServers": {
    "specfork": {
      "command": "/path/to/venv/bin/specfork",
      "args": ["mcp"],
      "env": { "NEBIUS_API_KEY": "..." }
    }
  }
}
```

Claude Code can also register it from the command line:

```bash
claude mcp add specfork -e NEBIUS_API_KEY=... -- \
  uvx --from "specfork[mcp] @ git+https://github.com/maestrosatyam/SpecFork" specfork mcp
```

Any other stdio MCP client: run the command `specfork mcp` (or the `uvx` form above) with the API key in
its environment. To use other models, also set `SPECFORK_FAST_MODEL`, `SPECFORK_DEEP_MODEL`,
`SPECFORK_IMPLEMENTERS` and `SPECFORK_MODELS_FILE` (an absolute path to your `specfork.toml`) in `env`.

A typical agent session:

1. `fork_spec(spec)` → the agent shows the user the questions and the executed examples.
2. The user picks options or writes their own answer.
3. `answer(run_id, answers={...}, other={...})` → clarified spec.
4. `get_tests(run_id, module="mypkg.billing")` → the agent writes the test file, then the implementation.
5. Optionally `refork(run_id)` to measure how unambiguous the clarified spec now is.
