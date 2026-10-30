// Mirrors docs/API_CONTRACT.md (v1). Keep in sync with the backend.

export type Preset = { id: string; title: string; spec: string; tagline: string; sample_run_id?: string };

export type RunStatus = "running" | "awaiting_answers" | "resolving" | "resolved" | "converging" | "error";
export type Stage = "frame" | "fanout" | "execute" | "cluster" | "explain" | "done";

export type Param = { name: string; type: string; description: string };
export type Signature = {
  name: string;
  params: Param[];
  returns: { type: string; description: string };
  docstring: string;
};

export type ProbeInput = { id: string; args: Record<string, unknown>; source: "model" | "fuzz"; note?: string };

export type Outcome = {
  ok: boolean;
  value_repr: string;
  error_type?: string;
  error_msg?: string;
};

export type ImplStatus = "pending" | "generated" | "rejected" | "executed" | "error";

export type Implementation = {
  id: string;
  index: number;
  model: string;
  status: ImplStatus;
  code?: string;
  reject_reason?: string;
  cluster_id?: string;
  outcomes?: Record<string, Outcome>;
};

export type Cluster = {
  id: string;
  label: string;
  impl_ids: string[];
  size: number;
  share: number;
  representative_impl_id: string;
  kind: "behavior" | "crash";
  summary?: string;
};

export type QuestionOption = {
  id: string;
  label: string;
  cluster_ids: string[];
  examples: { input_id: string; value_repr: string }[];
  impl_count?: number; // implementations choosing this option
  /** Assumption questions: the "change it" option. No implementation does this; cluster_ids is empty. */
  is_alternative?: boolean;
  /** Model-written example for an alternative, e.g. "parse('03/04/2025') -> '2025-04-03'". NOT executed. */
  note?: string;
  /** The user's own free-text ("Other…") answer, appended by the backend after resolution. Its examples ARE executed. */
  is_custom?: boolean;
};

export type Question = {
  id: string;
  text: string;
  why: string;
  /** "open": optional question the executed examples couldn't cover; no options, answered only via `other` free text. */
  kind: "ambiguity" | "likely_bug" | "assumption" | "open";
  witness_input_ids: string[]; // may be empty for assumptions
  affected_input_ids?: string[]; // assumption: inputs whose expected value depends on it
  agree_count?: number; // assumption: implementations sharing the consensus behaviour
  options: QuestionOption[];
  answer_option_id?: string;
};

export type CallRecord = {
  purpose: string;
  model: string;
  thinking: boolean;
  latency_s: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  ok: boolean;
  error?: string;
  request_id?: string;
  started_at: number;
  reasoning_excerpt?: string;
};

export type Convergence = {
  n: number;
  passed: number;
  agreement_after: number;
  clusters_after: number;
  status: "running" | "done" | "error";
  // Optional extras the backend sends (not in the v1 contract; UI degrades gracefully without them):
  executed?: number; // denominator for agreement_after
  implementations?: (Implementation & { passes_locked?: boolean })[];
};

export type Resolution = {
  answers: Record<string, string>;
  surviving_cluster_ids: string[];
  chosen_impl_id: string;
  clarified_spec: string;
  decisions: string[];
  tests_code: string;
  reference_code: string;
  locked_cases: { input_id: string; args: Record<string, unknown>; expected_repr: string }[];
  agreement_before: number;
  agreement_before_counts?: [number, number]; // optional extra: [matched, total]
  unlocked_input_ids?: string[]; // cases dropped from locked tests because an assumption was overridden
  open_input_ids?: string[]; // undecided split cases no question covered; left out of the locked tests
  custom_impl_id?: string; // implementation written for the user's free-text answers (in run.implementations)
  convergence?: Convergence;
};

export type LogLine = { t: number; stage: Stage | "resolve" | "converge"; msg: string };

export type Run = {
  id: string;
  created_at: number;
  updated_at: number;
  status: RunStatus;
  stage: Stage;
  error?: string;
  spec: string;
  preset_id?: string;
  is_sample: boolean;
  settings: {
    n_samples: number;
    fast_model: string;
    deep_model: string;
    assumptions?: boolean;
    /** Model ids used for the fan-out (round-robin). More than one = mixed-model run. */
    implementers?: string[];
    exception_types?: boolean;
  };
  signature?: Signature;
  inputs: ProbeInput[];
  implementations: Implementation[];
  clusters: Cluster[];
  questions: Question[];
  resolution?: Resolution;
  trace: CallRecord[];
  metrics: {
    total_cost_usd: number;
    prompt_tokens: number;
    completion_tokens: number;
    n_calls: number;
    wall_time_s: number;
  };
  log: LogLine[];
};

export type RunSummary = {
  id: string;
  created_at: number;
  status: RunStatus;
  spec: string;
  n_clusters: number;
  is_sample: boolean;
};

export type ModelRole = "fast" | "deep";

/** `model` (the provider model id) is optional; when present it lets the UI label trace calls of non-default models. */
export type AvailableModel = { key: string; label: string; provider_label?: string; roles: ModelRole[]; model?: string };

export type Health = {
  ok: boolean;
  llm_configured: boolean;
  models: { fast: string; deep: string };
  version: string;
  provider_label?: string;
  public_demo?: boolean;
  sandbox?: { ok: boolean; net_isolated: boolean };
  model_labels?: { fast: string; deep: string };
  available_models?: AvailableModel[];
};

export type CreateRunBody = {
  spec: string;
  n_samples?: number;
  preset_id?: string;
  fast_model?: string;
  deep_model?: string;
  assumptions?: boolean;
  /** Treat ValueError vs TypeError as different behaviours. Sent only when true. */
  exception_types?: boolean;
};

/** POST /answers body: one of `answers[qid]` (option id) or `other[qid]` (free text, 3..300 chars) per question. */
export type AnswersBody = { answers: Record<string, string>; other: Record<string, string> };
