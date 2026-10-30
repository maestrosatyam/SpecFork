# Recipes

## Check a spec from the terminal and keep the decision record

```bash
specfork fork "Split a restaurant bill evenly among n people and return the list of amounts each person pays, rounded to cents." \
  --module billing --out tests/ --reference billing_reference.py --decision-file .specfork.yaml --refork
```

Answer the questions interactively. You get `tests/test_<function>.py` (locked from executed behaviour), a
reference implementation, and `.specfork.yaml` with every decision, to commit next to the code.

## Let a coding agent ask before it writes code (MCP)

```json
{"mcpServers": {"specfork": {"command": "specfork", "args": ["mcp"], "env": {"NEBIUS_API_KEY": "…"}}}}
```

Ask the agent to "check this spec with SpecFork first". It calls `fork_spec` and relays the questions with their
executed examples. Then it calls `answer` with your choices, and implements against `get_tests` and
`get_clarified_spec`.

## Gate pull requests on unanswered spec questions (CI)

Keep one function spec per file in `specs/`, and use the action from `docs/examples/specfork-pr-check.yml`.
New specs get a PR comment listing their questions. Commit `.specfork/<spec>.answers.json`. The next run writes the
locked tests, and with `open-pr: "true"` opens a pull request containing them.

## Script it (JSON, two steps)

```bash
specfork fork --json "Return the median of a list of numbers." > run.json
jq '.questions[] | {id, text, options: [.options[] | {id, label}]}' run.json
echo '{"q0": "q0g1"}' > answers.json
specfork resolve run.json --answers answers.json --out tests/ --module stats
```

## Use a local or different model

```toml
# specfork.toml
[models.local]
model = "qwen2.5-coder:14b"
base_url = "http://localhost:11434/v1"
reasoning = "none"
price_per_m = [0, 0]
roles = ["fast"]
```

```bash
SPECFORK_FAST_MODEL=local specfork doctor
SPECFORK_FAST_MODEL=local specfork fork "…"
```

## Mix model families in the fan-out

```bash
SPECFORK_IMPLEMENTERS=lightning,qwen3-30b specfork fork "…"
```

The web UI then shows each behaviour's share per model. A split that follows model lines can be a model
difference rather than a spec ambiguity.

## Cheaper runs

`SPECFORK_ADAPTIVE_N=1` generates implementations in batches and stops once no new behaviour appears.
`SPECFORK_PROBE_ROUNDS=2` adds a second round of inputs aimed at the disagreements already found.
`SPECFORK_EXCEPTION_TYPES=1` also distinguishes `ValueError` from `TypeError`.

## Python API

```python
import asyncio
from specfork import Client

async def main() -> None:
    async with Client() as sf:
        run = await sf.fork("Truncate text to max_len characters, adding '...' if it was shortened.")
        answers = {q.id: q.options[0].id for q in run.open_questions}
        run = await sf.resolve(run, answers)
        print(run.resolution.clarified_spec)
        print(sf.tests(run, module="text_utils"))

asyncio.run(main())
```
