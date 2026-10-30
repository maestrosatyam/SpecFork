# SpecFork

**The ambiguity linter for specs.** Run it before your coding agent writes code: from your terminal, your agent
(MCP), your CI, or the web UI.

SpecFork asks a model for dozens of independent implementations of a one-paragraph function spec. It runs them
all in a sandbox and groups them by what they actually return. Every disagreement becomes a question backed by an
executed example. Your answers become a clarified spec and pytest tests locked from executed behaviour, and a
re-fork measures how many fresh implementations now agree with what you meant.

Code decides; the model explains. Clustering, witness selection, locked tests and agreement scores are
deterministic. Models write implementations and plain-English questions.

| Start here | |
|---|---|
| Install and use the CLI, or connect an agent over MCP | [CLI and MCP](CLI_AND_MCP.md) |
| Use other models (Nebius, NVIDIA NIM, vLLM, Ollama, OpenAI-compatible, Anthropic, Gemini) | [Providers](PROVIDERS.md) |
| How it works inside | [Architecture](ARCHITECTURE.md) |
| What the benchmark shows, including where it loses | [Evaluation](EVALUATION.md) |
| Sandbox design and the reporting policy | [Security](SECURITY.md) |

Default models: **NVIDIA Nemotron 3.5 Lightning** (framing, fan-out, re-fork) and **NVIDIA Nemotron 3 Ultra**
(questions, silent assumptions, clarified spec), served by **Nebius Token Factory**.
Source: [github.com/maestrosatyam/SpecFork](https://github.com/maestrosatyam/SpecFork) (MIT).
