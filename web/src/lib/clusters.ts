// Cluster colouring + answer-driven filtering (unit-tested in clusters.test.ts).
import type { Cluster, Implementation, Question, QuestionOption, Run } from "../types";

/**
 * Colour-blind-friendly categorical palette (Okabe–Ito derived, lifted for a dark background).
 * Order chosen so the first 3–4 clusters are maximally distinct under deuteranopia/protanopia.
 */
export const CLUSTER_COLORS = [
  "#56B4E9", // sky
  "#F5A524", // orange
  "#2FC79E", // bluish green
  "#E68AC0", // reddish purple
  "#F0E442", // yellow
  "#8E9BFF", // periwinkle
  "#FF7A45", // vermillion
  "#B8C4D6", // slate
] as const;

export const CRASH_COLOR = "#E5484D";

export type ClusterStyle = { color: string; crash: boolean; label: string };

/** Stable colour per cluster: behaviour clusters take palette slots in order; crash clusters are red/striped. */
export function clusterStyles(clusters: Cluster[]): Record<string, ClusterStyle> {
  const out: Record<string, ClusterStyle> = {};
  let k = 0;
  const sorted = [...clusters].sort((a, b) => a.label.localeCompare(b.label));
  for (const c of sorted) {
    if (c.kind === "crash") out[c.id] = { color: CRASH_COLOR, crash: true, label: c.label };
    else out[c.id] = { color: CLUSTER_COLORS[k++ % CLUSTER_COLORS.length], crash: false, label: c.label };
  }
  return out;
}

export function ambiguityQuestions(qs: Question[]): Question[] {
  return qs.filter((q) => q.kind === "ambiguity");
}

export function assumptionQuestions(qs: Question[]): Question[] {
  return qs.filter((q) => q.kind === "assumption");
}

export function likelyBugQuestions(qs: Question[]): Question[] {
  return qs.filter((q) => q.kind === "likely_bug");
}

/** Questions the user must answer before locking in: ambiguities and silent assumptions. */
export function answerableQuestions(qs: Question[]): Question[] {
  return qs.filter((q) => q.kind === "ambiguity" || q.kind === "assumption");
}

/**
 * Given the user's (possibly partial) selections, which clusters are still consistent with them?
 * Returns null when nothing constrains (meaning: no filtering, everything is highlighted).
 * Intersection over answered questions of the chosen option's cluster_ids. Alternative options
 * (overriding a silent assumption) and custom free-text options are ignored: no forked implementation
 * does them, so they say nothing about which existing clusters survive.
 */
export function activeClusterIds(
  questions: Question[],
  answers: Record<string, string>,
  excludeQuestionId?: string,
): Set<string> | null {
  let active: Set<string> | null = null;
  for (const q of answerableQuestions(questions)) {
    if (q.id === excludeQuestionId) continue;
    const optId = answers[q.id];
    if (!optId) continue;
    const opt = q.options.find((o) => o.id === optId);
    if (!opt || ignoresClusters(opt)) continue;
    const ids = new Set(opt.cluster_ids);
    const prev: Set<string> | null = active;
    active = prev === null ? ids : new Set([...prev].filter((id: string) => ids.has(id)));
  }
  return active;
}

/**
 * Is this option achievable together with the user's answers to the *other* questions?
 * Alternatives are always compatible; otherwise its clusters must intersect the clusters still alive.
 */
export function optionCompatible(
  questions: Question[],
  answers: Record<string, string>,
  q: Question,
  opt: QuestionOption,
): boolean {
  if (ignoresClusters(opt)) return true;
  const alive = activeClusterIds(questions, answers, q.id);
  if (alive === null) return true;
  return opt.cluster_ids.some((id) => alive.has(id));
}

/** Options that never constrain cluster highlighting: assumption overrides and the user's own free-text answers. */
export function ignoresClusters(opt: QuestionOption): boolean {
  return !!opt.is_alternative || !!opt.is_custom;
}

export const OTHER_MIN = 3;
export const OTHER_MAX = 300;

/** A free-text "Other…" answer counts once it has at least OTHER_MIN non-space characters. */
export function otherValid(text: string | undefined): boolean {
  return typeof text === "string" && text.trim().length >= OTHER_MIN;
}

/** Answered = a known option is selected, OR a valid free-text answer is given. */
export function isAnswered(q: Question, answers: Record<string, string>, other: Record<string, string> = {}): boolean {
  const a = answers[q.id];
  if (a && q.options.some((o) => o.id === a)) return true;
  return otherValid(other[q.id]);
}

export function answeredCount(
  questions: Question[],
  answers: Record<string, string>,
  other: Record<string, string> = {},
): number {
  return answerableQuestions(questions).filter((q) => isAnswered(q, answers, other)).length;
}

export function allAnswered(
  questions: Question[],
  answers: Record<string, string>,
  other: Record<string, string> = {},
): boolean {
  const qs = answerableQuestions(questions);
  return qs.length > 0 && qs.every((q) => isAnswered(q, answers, other));
}

/**
 * The POST /answers body: exactly one of option or free text per answerable question. A selected option wins
 * when both are somehow present (the UI clears one when the other is chosen). Free text is trimmed and capped.
 */
export function buildAnswersBody(
  questions: Question[],
  answers: Record<string, string>,
  other: Record<string, string> = {},
): { answers: Record<string, string>; other: Record<string, string> } {
  const outA: Record<string, string> = {};
  const outO: Record<string, string> = {};
  for (const q of answerableQuestions(questions)) {
    const a = answers[q.id];
    if (a && q.options.some((o) => o.id === a)) outA[q.id] = a;
    else if (otherValid(other[q.id])) outO[q.id] = other[q.id].trim().slice(0, OTHER_MAX);
  }
  return { answers: outA, other: outO };
}

/** @deprecated kept for compatibility; same as allAnswered (ambiguities + assumptions). */
export const allAmbiguitiesAnswered = allAnswered;

/** Number of implementations whose cluster backs these cluster ids. */
export function optionImplCount(clusters: Cluster[], clusterIds: string[]): number {
  const set = new Set(clusterIds);
  return clusters.filter((c) => set.has(c.id)).reduce((acc, c) => acc + c.size, 0);
}

/** Implementations choosing an option: the server's impl_count when present, else derived from clusters. */
export function optionCount(clusters: Cluster[], opt: QuestionOption): number {
  if (typeof opt.impl_count === "number") return opt.impl_count;
  if (ignoresClusters(opt)) return 0;
  return optionImplCount(clusters, opt.cluster_ids);
}

/** Executed implementations (the denominator used for cluster shares). */
export function executedCount(impls: Implementation[]): number {
  return impls.filter((i) => i.status === "executed" || i.cluster_id).length;
}

/** Initial answers taken from the run (server may have pre-filled answer_option_id). */
export function answersFromRun(run: Run): Record<string, string> {
  const out: Record<string, string> = {};
  for (const q of run.questions) if (q.answer_option_id) out[q.id] = q.answer_option_id;
  if (run.resolution)
    for (const [k, v] of Object.entries(run.resolution.answers)) if (typeof v === "string" && v) out[k] = v;
  return out;
}

export const STAGES: { id: "frame" | "fanout" | "execute" | "cluster" | "explain"; label: string; blurb: string }[] = [
  { id: "frame", label: "Frame", blurb: "Pin down a signature and probe inputs" },
  { id: "fanout", label: "Fan-out", blurb: "Independent implementations" },
  { id: "execute", label: "Execute", blurb: "Run every impl on every probe in a sandbox" },
  { id: "cluster", label: "Cluster", blurb: "Group by observable behaviour" },
  { id: "explain", label: "Explain", blurb: "Turn disagreements into questions" },
];

export function stageIndex(stage: string): number {
  if (stage === "done") return STAGES.length;
  const i = STAGES.findIndex((s) => s.id === stage);
  return i < 0 ? 0 : i;
}
