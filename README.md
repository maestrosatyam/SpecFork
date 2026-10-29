# SpecFork

**Your spec means more than one thing. Find out which, before your coding agent guesses.**

SpecFork takes a one-paragraph function spec, has **NVIDIA Nemotron 3.5 Lightning** (an NVIDIA open model,
served by **Nebius Token Factory**) write dozens of independent implementations, *runs* them all in a
sandbox, and groups them by what they actually do. Every place they disagree becomes a concrete witness
input and a one-click clarifying question, written by **NVIDIA Nemotron 3 Ultra** with reasoning on. Your
answers become a clarified spec, a pytest file locked from executed behaviour, and a reference
implementation. A final **re-fork** measures how many fresh, independent implementations now agree with
what you meant.

> Hackathon: Nebius × NVIDIA Global AI Hackathon 2026, track **Coding and Agentic Engineering**.
> Live demo: _see the Devpost entry / `submission/DEVPOST_SUBMISSION.md`_ · License: MIT

```
"Split a restaurant bill evenly among n people. Return how much each person pays, rounded to cents."

            ┌─ A  [33.34, 33.33, 33.33]  leftover cents go to the first people
 24 impls ──┼─ B  [33.33, 33.33, 33.33]  everyone pays the rounded share (a cent vanishes)
            ├─ C  [33.34, 33.34, 33.34]  everyone rounds up
            └─ …  n = 0 → [] vs ValueError
```

## How it works

| Step | What happens | Who decides |
|---|---|---|
| 1. Frame | Lightning (reasoning on) proposes a typed signature and 14–18 edge-case probe inputs; plus deterministic type-driven fuzz inputs | model proposes, code validates |
| 2. Fan-out | N independent implementations from Lightning (reasoning off, temperature 1.0, distinct seeds) | model |
| 3. Execute | each implementation passes an AST allow-list, then runs on every probe in an isolated subprocess | **code** |
| 4. Cluster | implementations with identical canonical outputs on all probes form one *behaviour*; witness inputs are chosen by greedy pair-separation | **code** |
| 5. Explain | Nemotron 3 Ultra (reasoning on) turns each split into a plain-English question, labels likely bugs, summarises clusters | model, grounded in executed outputs |
| 6. Resolve | your answers select the surviving behaviour; tests are generated **deterministically** from its executed outputs; Ultra rewrites the spec | **code** + model for prose |
| 7. Re-fork | N fresh implementations of the clarified spec are run against the locked tests → agreement before vs after | **code** |

Every Nebius call (model ID, latency, tokens, cost, reasoning excerpt) is shown in the app's
**Under the hood** panel and stored with the run.

## NVIDIA models and Nebius Token Factory

| Role | Model (Nebius Token Factory ID) | Settings |
|---|---|---|
| framing, fan-out, re-fork | `nvidia/Nemotron-3_5-Lightning` | `chat_template_kwargs.enable_thinking` on for framing, off for fan-out |
| explaining disagreements, clarified spec | `nvidia/Nemotron-3-Ultra-550b-a55b` | reasoning on for explain |

Endpoint: `https://api.tokenfactory.nebius.com/v1` (OpenAI-compatible chat completions), see
[`app/llm.py`](app/llm.py). To confirm the integration yourself: `make probe` writes
`evidence/nebius_model_runtime_probe.json` with model IDs, latencies, token usage and outputs
(no secrets).

## Quick start

```bash
git clone <this repo> && cd <repo>
cp .env.example .env            # add NEBIUS_API_KEY
make setup                      # Python 3.12 venv (uv) + frontend deps
make test                       # offline tests (no API key needed)
make probe                      # live Nebius/NVIDIA probe
make build && make dev          # http://localhost:8000
```

Frontend development with hot reload: `make dev` in one shell, `make web` in another (Vite proxies `/api`).
A fully simulated flow is available at `/?mock=1` (clearly labelled; no inference).

## Repository map

```
app/            FastAPI backend: llm.py (Nebius client), pipeline.py (orchestration), sandbox.py + _harness.py
                (isolated execution), cluster.py (behaviour clustering, witnesses), canon.py, store.py, main.py
web/            React + TypeScript + Tailwind frontend
tests/          offline unit/integration tests (scripted fake LLM; no network)
evals/          benchmark (32 hand-written specs with hidden reference implementations) + live eval runner
scripts/        probe, deploy (Cloud Run), sample-run recorder, video production pipeline
evidence/       runtime probe, test logs, evaluation results, security checks
submission/     Devpost text, compliance matrix, architecture, feedback, demo video assets
research/       idea selection record
oss/            separate open-source contribution (NVIDIA NeMo Agent Toolkit)
```

## Security

Generated code is treated as hostile: AST allow-list, proxied stdlib modules, restricted builtins,
`python -I -S` subprocess with a stripped environment, rlimits (CPU, memory, file size, fds), per-call
timeouts, a fresh network namespace (no network), a non-dumpable server process, and a non-root container.
Details and executed tests: [`evidence/SECURITY_CHECKS.md`](evidence/SECURITY_CHECKS.md).

## Prior art and honesty

The core signal (sample many programs, execute, cluster, ask) is known from research: ClarifyGPT
(Mu et al., 2023), TiCoder (Lahiri et al., 2022), AlphaCode's behavioural clustering. SpecFork's
contribution is the interactive product loop: witness-backed questions, deterministic locked tests, and a
measured re-fork. SpecFork cannot surface an ambiguity that every sampled implementation resolves the same
way. Evaluation results, including where baselines do as well, are in
[`evidence/EVALUATION_RESULTS.md`](evidence/EVALUATION_RESULTS.md).

## License

MIT, see [LICENSE](LICENSE).
