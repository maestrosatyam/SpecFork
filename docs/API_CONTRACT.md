# SpecFork API contract (v1)

Backend: FastAPI, same origin as the built frontend (served from `/`). All JSON.

## Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/health` | – | `{ok, llm_configured, models: {fast, deep}, version}` |
| GET | `/api/presets` | – | `Preset[]` |
| POST | `/api/runs` | `{spec: string, n_samples?: 8..40 (default 24), preset_id?: string}` | `{id}` (HTTP 429 with `{detail}` when rate limited, 503 if LLM not configured) |
| GET | `/api/runs` | – | `RunSummary[]` (recent + sample runs) |
| GET | `/api/runs/{id}` | – | `Run` |
| GET | `/api/runs/{id}/events` | – | Server-Sent Events. `event: snapshot` with `data: Run` JSON (throttled, ≤4/s); `event: end` when status leaves `running`/`resolving`/`converging`. |
| POST | `/api/runs/{id}/answers` | `{answers: {[question_id]: option_id}}` | `Run` (status becomes `resolving`, then `resolved`; follow via SSE) |
| POST | `/api/runs/{id}/converge` | `{n_samples?: number}` | `Run` (status `converging` → `resolved` with `resolution.convergence`) |
| GET | `/api/runs/{id}/export.md` | – | Markdown bundle (clarified spec + tests + reference impl) |
| GET | `/api/runs/{id}/tests.py` | – | pytest file text |

## Types (TypeScript notation)

```ts
type Preset = { id: string; title: string; spec: string; tagline: string; sample_run_id?: string };

type RunStatus = "running" | "awaiting_answers" | "resolving" | "resolved" | "converging" | "error";
type Stage = "frame" | "fanout" | "execute" | "cluster" | "explain" | "done";

type Param = { name: string; type: string; description: string };
type Signature = { name: string; params: Param[]; returns: { type: string; description: string }; docstring: string };

type ProbeInput = { id: string; args: Record<string, unknown>; source: "model" | "fuzz"; note?: string };

type Outcome = {
  ok: boolean;              // returned without exception
  value_repr: string;       // canonical repr, e.g. "[33.34, 33.33, 33.33]" or "ValueError"
  error_type?: string;      // exception class when ok=false, or "Timeout"
  error_msg?: string;
};

type Implementation = {
  id: string; index: number; model: string;
  status: "pending" | "generated" | "rejected" | "executed" | "error";
  code?: string;
  reject_reason?: string;    // static safety check failure / no function
  cluster_id?: string;
  outcomes?: Record<string, Outcome>;   // keyed by ProbeInput.id
};

type Cluster = {
  id: string; label: string;            // "A", "B", ...
  impl_ids: string[]; size: number; share: number; // share of executed impls
  representative_impl_id: string;
  kind: "behavior" | "crash";           // crash = raises on most inputs
  summary?: string;                      // one-line plain-English summary from the deep model
};

type QuestionOption = {
  id: string; label: string;             // short answer text, e.g. "Give the extra cent to the first person"
  cluster_ids: string[];
  examples: { input_id: string; value_repr: string }[];
};

type Question = {
  id: string; text: string; why: string;
  kind: "ambiguity" | "likely_bug";
  witness_input_ids: string[];
  options: QuestionOption[];
  answer_option_id?: string;
};

type CallRecord = {
  purpose: string; model: string; thinking: boolean; latency_s: number;
  prompt_tokens: number; completion_tokens: number; cost_usd: number;
  ok: boolean; error?: string; request_id?: string; started_at: number;
  reasoning_excerpt?: string;            // first ~600 chars of Nemotron reasoning, when thinking=true
};

type Resolution = {
  answers: Record<string, string>;
  surviving_cluster_ids: string[];
  chosen_impl_id: string;
  clarified_spec: string;
  decisions: string[];                   // bullet list of decisions made
  tests_code: string;                    // pytest file, generated deterministically from witnesses
  reference_code: string;
  locked_cases: { input_id: string; args: Record<string, unknown>; expected_repr: string }[];
  agreement_before: number;              // share of original impls matching chosen behaviour on all locked cases
  convergence?: {
    n: number; passed: number; agreement_after: number;  // share of re-forked impls passing all locked cases
    clusters_after: number; status: "running" | "done" | "error";
  };
};

type Run = {
  id: string; created_at: number; updated_at: number;
  status: RunStatus; stage: Stage; error?: string;
  spec: string; preset_id?: string; is_sample: boolean;  // is_sample: cached run recorded earlier, labelled in UI
  settings: { n_samples: number; fast_model: string; deep_model: string };
  signature?: Signature;
  inputs: ProbeInput[];
  implementations: Implementation[];
  clusters: Cluster[];
  questions: Question[];
  resolution?: Resolution;
  trace: CallRecord[];
  metrics: { total_cost_usd: number; prompt_tokens: number; completion_tokens: number; n_calls: number; wall_time_s: number };
  log: { t: number; stage: Stage | "resolve" | "converge"; msg: string }[];
};

type RunSummary = { id: string; created_at: number; status: RunStatus; spec: string; n_clusters: number; is_sample: boolean };
```

## UX flow
1. User writes/picks a spec → **Fork it**.
2. Live: stages progress; a grid of N implementation tiles fills (pending → generated → executed, coloured by cluster once clustered).
3. `awaiting_answers`: "Your spec has K meanings". Cluster bar + question cards. Each option shows witness input + resulting outputs and how many implementations chose it. Selecting options highlights/fades clusters.
4. **Lock it in** → `resolving` → clarified spec (diff vs original), decisions, generated pytest, reference implementation, agreement_before.
5. **Re-fork the clarified spec** → `converging` → agreement_after vs agreement_before (hero metric).
6. Trace panel: every Nebius Token Factory call (model, latency, tokens, cost, reasoning excerpt).
