// Cluster colouring + answer-driven filtering (unit-tested in clusters.test.ts).
import type { Cluster, Implementation, Question, Run } from "../types";

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

export function likelyBugQuestions(qs: Question[]): Question[] {
  return qs.filter((q) => q.kind === "likely_bug");
}

/**
 * Given the user's (possibly partial) selections, which clusters are still consistent with them?
 * Returns null when nothing is selected (meaning: no filtering, everything is highlighted).
 * Intersection over answered ambiguity questions of the chosen option's cluster_ids.
 */
export function activeClusterIds(questions: Question[], answers: Record<string, string>): Set<string> | null {
  let active: Set<string> | null = null;
  for (const q of ambiguityQuestions(questions)) {
    const optId = answers[q.id];
    if (!optId) continue;
    const opt = q.options.find((o) => o.id === optId);
    if (!opt) continue;
    const ids = new Set(opt.cluster_ids);
    const prev: Set<string> | null = active;
    active = prev === null ? ids : new Set([...prev].filter((id: string) => ids.has(id)));
  }
  return active;
}

export function allAmbiguitiesAnswered(questions: Question[], answers: Record<string, string>): boolean {
  const amb = ambiguityQuestions(questions);
  return amb.length > 0 && amb.every((q) => !!answers[q.id] && q.options.some((o) => o.id === answers[q.id]));
}

/** Number of implementations whose cluster backs this option. */
export function optionImplCount(clusters: Cluster[], clusterIds: string[]): number {
  const set = new Set(clusterIds);
  return clusters.filter((c) => set.has(c.id)).reduce((acc, c) => acc + c.size, 0);
}

/** Executed implementations (the denominator used for cluster shares). */
export function executedCount(impls: Implementation[]): number {
  return impls.filter((i) => i.status === "executed" || i.cluster_id).length;
}

/** Initial answers taken from the run (server may have pre-filled answer_option_id). */
export function answersFromRun(run: Run): Record<string, string> {
  const out: Record<string, string> = {};
  for (const q of run.questions) if (q.answer_option_id) out[q.id] = q.answer_option_id;
  if (run.resolution) Object.assign(out, run.resolution.answers);
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
