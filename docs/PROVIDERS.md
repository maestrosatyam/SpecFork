# Models and providers

SpecFork talks to models through **profiles**: small TOML entries that say where a model lives, how to
authenticate, how to switch reasoning on and off, what it costs, and which roles it may play. Profiles are
data, not code. The built-in profiles live in [`specfork/models.toml`](../specfork/models.toml); you add
or override profiles in a `specfork.toml`.

The defaults are **NVIDIA Nemotron 3.5 Lightning** (fast role) and **NVIDIA Nemotron 3 Ultra** (deep role),
both served by **Nebius Token Factory**. The only thing you need for them is `NEBIUS_API_KEY`.

## Where profiles come from

1. `specfork/models.toml` (built in: `lightning`, `ultra`).
2. The file named by `SPECFORK_MODELS_FILE`, or else `./specfork.toml` in the current directory if it exists.

Profiles are merged by key, field by field: a `[models.ultra]` table in your file with only `price_per_m`
changes the price and keeps every other built-in field. Profiles are validated when loaded; an unknown
`api` or `reasoning` value, a missing `model` or a malformed price is an error.

## `specfork.toml` schema

Each profile is a table `[models.<key>]`. The key is the name you use in settings and on the CLI
(`--fast <key>`, `SPECFORK_DEEP_MODEL=<key>`); a model id is also accepted wherever a key is.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `model` | string | **required** | the provider's model id, sent in each request |
| `api` | `"openai_compat"` \| `"anthropic"` \| `"gemini"` | `"openai_compat"` | which adapter builds and parses requests |
| `base_url` | string | Anthropic: `https://api.anthropic.com`; Gemini: `https://generativelanguage.googleapis.com`; otherwise required | API root. `openai_compat` posts to `<base_url>/chat/completions`, `anthropic` to `<base_url>/v1/messages`, `gemini` to `<base_url>/v1beta/models/<model>:generateContent` |
| `key_env` | string | none | name of the environment variable holding the API key (never the key itself). The name must end in `_KEY` (for example `OPENROUTER_API_KEY`). Omit it for local servers that need no key |
| `label` | string | the model id | display name (CLI, web UI, Markdown export) |
| `provider_label` | string | `""` | display name of the provider, for example `"Nebius Token Factory"` |
| `reasoning` | see [Reasoning modes](#reasoning-modes) | `"none"` | how reasoning is switched on and off |
| `reasoning_extras` | table of tables | `{}` | `chat_template_kwargs` only: extra template arguments per effort level, merged in when reasoning is on, for example `{ medium = { medium_effort = true } }` |
| `seed` | bool | `false` | send the per-implementation `seed` (OpenAI-compatible and Gemini). Turn it on only if the provider honours it; `specfork doctor` checks |
| `json_schema` | bool | `false` | request JSON output natively (`response_format: {type: json_object}` or Gemini `responseMimeType`). SpecFork always parses JSON tolerantly, so this is optional |
| `price_per_m` | `[input, output]` | none | USD per 1M prompt and completion tokens. Used for the cost shown per call and for the daily spend cap. See [Pricing](#pricing-and-the-public-demo-rule) |
| `max_concurrency` | int | 16 | accepted and validated, but not yet enforced per profile; the global `LLM_CONCURRENCY` bounds concurrent calls |
| `roles` | list of `"fast"` / `"deep"` | `[]` | which roles the **web UI** offers this profile for. The CLI, library and settings can use any profile in any role |

## Roles

| Role | Setting | Default | Used for |
|---|---|---|---|
| fast | `SPECFORK_FAST_MODEL` (CLI `--fast`) | `lightning` | framing, and the fan-out and re-fork unless implementers are set |
| deep | `SPECFORK_DEEP_MODEL` (CLI `--deep`) | `ultra` | explaining disagreements, the silent-assumption review, the clarified spec, implementing free-text answers |
| implementers | `SPECFORK_IMPLEMENTERS` | the fast model | comma-separated profile keys for a **mixed-model fan-out** |

With `SPECFORK_IMPLEMENTERS=lightning,qwen,local` the N implementations are assigned round-robin
(`m0` → `lightning`, `m1` → `qwen`, `m2` → `local`, `m3` → `lightning`, …), and the re-fork uses the same
list. Different models disagree in different ways, so a mixed fan-out can expose decisions a single model
always makes the same way. Passing `--fast` on the CLI (or `fast_model` to `Client.fork`, or choosing a fast
model in the web UI) uses that one model for the whole fan-out instead.

Legacy names `MODEL_FAST` and `MODEL_DEEP` (profile keys or model ids) are still accepted.

## Reasoning modes

SpecFork asks for reasoning with a generic intent (on/off plus an effort level: the pipeline uses
`medium` for the deep model; the framing call has reasoning off unless `FRAME_THINKING=1`). Each mode
translates the intent for its API:

| `reasoning` | API | Reasoning on | Reasoning off |
|---|---|---|---|
| `chat_template_kwargs` | `openai_compat` | `"chat_template_kwargs": {"enable_thinking": true, ...reasoning_extras[effort]}` | `"chat_template_kwargs": {"enable_thinking": false}` |
| `reasoning_effort` | `openai_compat` | `"reasoning_effort": "<effort>"` (default `medium`) | nothing sent |
| `anthropic_thinking` | `anthropic` | `"thinking": {"type": "enabled", "budget_tokens": B}`, `max_tokens` raised to at least `B + 1024`, no `temperature` | no `thinking`; `temperature` capped at 1.0 |
| `gemini_thinking` | `gemini` | `"thinkingConfig": {"thinkingBudget": B, "includeThoughts": true}` | `"thinkingConfig": {"thinkingBudget": 0}` |
| `none` | any | nothing sent; the model is used as is | nothing sent |

Thinking budgets `B` by effort: `low` 2048, `medium` 8192, `high` 16384 tokens.

`chat_template_kwargs` is for models whose chat template has a thinking switch (NVIDIA Nemotron, Qwen) on
servers that pass template arguments through (Nebius Token Factory, NVIDIA NIM, vLLM, SGLang).
`reasoning_effort` is for OpenAI-style reasoning models. Use `none` for anything else: a plain profile never
sends `chat_template_kwargs`, which some providers reject.

Reasoning text is separated from the answer whether it arrives as `reasoning_content` / `reasoning`, as
inline `<think>…</think>` blocks, as Anthropic `thinking` blocks or as Gemini `thought` parts. An excerpt is
kept in each call record. If a reasoning call fails to return parseable JSON, the pipeline retries the same
call with reasoning off.

## Examples

All examples go into a `specfork.toml` in the directory you run SpecFork from (or the file named by
`SPECFORK_MODELS_FILE`). Prices below are placeholders: put in your provider's real prices.

### Nebius Token Factory (built in)

Nothing to configure beyond `NEBIUS_API_KEY`. For reference, the built-in profile for the fast role:

```toml
[models.lightning]
label = "NVIDIA Nemotron 3.5 Lightning"
provider_label = "Nebius Token Factory"
api = "openai_compat"
base_url = "https://api.tokenfactory.nebius.com/v1"
model = "nvidia/Nemotron-3_5-Lightning"
key_env = "NEBIUS_API_KEY"
reasoning = "chat_template_kwargs"
seed = true
json_schema = true
price_per_m = [0.06, 0.24]
roles = ["fast"]
```

The `ultra` profile (`nvidia/Nemotron-3-Ultra-550b-a55b`, `price_per_m = [1.00, 3.00]`, role `deep`) adds
`reasoning_extras = { medium = { medium_effort = true }, low = { medium_effort = true } }`. Another Token
Factory model is one more table with the same `base_url` and `key_env`.

### NVIDIA NIM (hosted API catalog or self-hosted)

```toml
[models.nim-nemotron]
label = "Nemotron via NVIDIA NIM"
provider_label = "NVIDIA NIM"
base_url = "https://integrate.api.nvidia.com/v1"   # or http://localhost:8000/v1 for a self-hosted NIM
model = "nvidia/<model-id>"
key_env = "NVIDIA_API_KEY"
reasoning = "chat_template_kwargs"                  # if the model's template has enable_thinking; else "none"
price_per_m = [0.0, 0.0]
roles = ["fast", "deep"]
```

### vLLM or SGLang (self-hosted)

```toml
[models.vllm-local]
label = "Local model (vLLM)"
base_url = "http://localhost:8000/v1"
model = "Qwen/Qwen3-8B"
reasoning = "chat_template_kwargs"   # Qwen3 templates accept enable_thinking
seed = true
json_schema = true
price_per_m = [0.0, 0.0]
roles = ["fast"]
```

### Ollama

```toml
[models.ollama]
label = "Ollama"
base_url = "http://localhost:11434/v1"
model = "qwen2.5-coder:7b"
reasoning = "none"
price_per_m = [0.0, 0.0]
roles = ["fast"]
```

### OpenRouter (or any other OpenAI-compatible endpoint)

```toml
[models.openrouter-coder]
label = "Coder via OpenRouter"
provider_label = "OpenRouter"
base_url = "https://openrouter.ai/api/v1"
model = "<vendor>/<model>"
key_env = "OPENROUTER_API_KEY"
reasoning = "none"
price_per_m = [0.20, 0.80]
roles = ["fast"]

[models.openai-reasoner]
label = "OpenAI reasoning model"
base_url = "https://api.openai.com/v1"
model = "<model-id>"
key_env = "OPENAI_API_KEY"
reasoning = "reasoning_effort"
json_schema = true
price_per_m = [1.10, 4.40]
roles = ["deep"]
```

The same pattern works for Together, Groq, Fireworks and LM Studio.

### Anthropic

> The Anthropic adapter is unit-tested against recorded request/response shapes; it has not yet been
> verified live.

```toml
[models.claude]
label = "Claude"
provider_label = "Anthropic"
api = "anthropic"
model = "<model-id>"
key_env = "ANTHROPIC_API_KEY"
reasoning = "anthropic_thinking"
price_per_m = [3.0, 15.0]
roles = ["deep"]
```

Requests go to `/v1/messages` with `x-api-key` and `anthropic-version: 2023-06-01`. System messages are
joined into `system`; JSON mode appends "Reply with JSON only." to it. `seed` and `json_schema` are ignored.

### Gemini

> The Gemini adapter is unit-tested against recorded request/response shapes; it has not yet been
> verified live.

```toml
[models.gemini]
label = "Gemini"
provider_label = "Google"
api = "gemini"
model = "<model-id>"
key_env = "GEMINI_API_KEY"
reasoning = "gemini_thinking"
json_schema = true
price_per_m = [0.30, 2.50]
roles = ["fast", "deep"]
```

Requests go to `generateContent` with `x-goog-api-key`; system messages become `systemInstruction`, and
assistant turns use the `model` role.

### Putting it together

```bash
# .env (or the environment)
NEBIUS_API_KEY=...
OPENROUTER_API_KEY=...
SPECFORK_FAST_MODEL=lightning
SPECFORK_DEEP_MODEL=ultra
SPECFORK_IMPLEMENTERS=lightning,openrouter-coder,ollama
```

```bash
specfork doctor                          # checks lightning, ultra, openrouter-coder and ollama
specfork fork --deep claude "<spec>"     # one-off: Anthropic for the explanations
```

## Pricing and the public-demo rule

`price_per_m` drives two things: the cost recorded for every call (and shown in the CLI, the web UI and the
trace), and the server's daily spend cap (`DAILY_BUDGET_USD`). A call to a profile without a price is
recorded with cost 0 and `priced: false`.

- **Local use:** unpriced profiles are allowed. Costs simply read 0 for them; `specfork doctor` reports
  `"price": "MISSING"`.
- **Public demo (`SPECFORK_PUBLIC_DEMO=1`):** an unpriced profile could silently disable the budget cap, so
  the server refuses to start if the configured fast, deep or implementer profile has no price, and the web
  UI never offers unpriced profiles. Use `price_per_m = [0.0, 0.0]` only for models that really cost
  nothing per token (for example local servers).

In the web UI a visitor may choose only profiles that list the role in `roles`, have their API key
configured and, in public-demo mode, are priced.

## `specfork doctor`

`specfork doctor` checks the sandbox and every profile used by the current settings (fast, deep and
implementers); `specfork doctor --all` checks every known profile. For each profile it prints one JSON line:

| Key | Meaning |
|---|---|
| `price` | `yes` or `MISSING` |
| `reachable` | `yes (<latency>s)`, `no key (<KEY_ENV>)` or `NO: <error>` |
| `json` | whether a small JSON task came back as valid JSON with the right answer |
| `seed` | (`seed = true` only) whether two calls with the same seed returned the same text |
| `reasoning` | (`reasoning` other than `none`) whether turning reasoning on produced separate reasoning text |

The first line reports whether the sandbox works and whether network isolation is in effect. The exit code
is 1 if any profile is unreachable or has no key. `make probe` runs the same command.
