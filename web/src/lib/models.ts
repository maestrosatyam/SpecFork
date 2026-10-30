// Model / provider display names, derived from /api/health (unit-tested in models.test.ts).
import { createContext, useContext } from "react";
import type { AvailableModel, Health, ModelRole, Run } from "../types";
import { modelFamily, shortModel } from "./format";

/** Fallbacks used when health is unavailable (or an older backend omits the labels). */
export const DEFAULT_FAST_LABEL = "NVIDIA Nemotron 3.5 Lightning";
export const DEFAULT_DEEP_LABEL = "NVIDIA Nemotron 3 Ultra";
export const DEFAULT_PROVIDER_LABEL = "Nebius Token Factory";

export type Labels = {
  fast: string;
  deep: string;
  provider: string;
  /** Shared family name for "Powered by …" copy, e.g. "NVIDIA Nemotron". */
  family: string;
  /** Default model ids (health.models), used to map trace model ids to labels. */
  ids: { fast?: string; deep?: string };
  available: AvailableModel[];
};

/** Longest shared leading words of two labels ("NVIDIA Nemotron 3.5 Lightning" + "NVIDIA Nemotron 3 Ultra" -> "NVIDIA Nemotron"). */
export function commonFamily(a: string, b: string): string {
  if (a === b) return a;
  const wa = a.split(/\s+/);
  const wb = b.split(/\s+/);
  const out: string[] = [];
  for (let i = 0; i < Math.min(wa.length, wb.length) && wa[i] === wb[i]; i++) out.push(wa[i]);
  // Drop trailing version-ish tokens ("3") so the family reads as a name.
  while (out.length && /^[\d.]+$/.test(out[out.length - 1])) out.pop();
  return out.length ? out.join(" ") : `${a} and ${b}`;
}

export function labelsFromHealth(h: Health | null | undefined): Labels {
  const fast = h?.model_labels?.fast?.trim() || DEFAULT_FAST_LABEL;
  const deep = h?.model_labels?.deep?.trim() || DEFAULT_DEEP_LABEL;
  const provider = h?.provider_label?.trim() || DEFAULT_PROVIDER_LABEL;
  return {
    fast,
    deep,
    provider,
    family: commonFamily(fast, deep),
    ids: { fast: h?.models?.fast, deep: h?.models?.deep },
    available: Array.isArray(h?.available_models) ? h!.available_models! : [],
  };
}

export const DEFAULT_LABELS = labelsFromHealth(null);

/** Human label for a model id or registry key; falls back to the id-derived family name. */
export function modelLabel(model: string | undefined, labels: Labels): string {
  if (!model) return "";
  if (model === labels.ids.fast) return labels.fast;
  if (model === labels.ids.deep) return labels.deep;
  const reg = labels.available.find((m) => m.key === model || (!!m.model && m.model === model));
  if (reg) return reg.label;
  return modelFamily(model) || shortModel(model);
}

/** Labels for the models a specific run used (a run may have picked non-default models). */
export function runModelLabels(run: Run, labels: Labels): { fast: string; deep: string } {
  return {
    fast: modelLabel(run.settings.fast_model, labels) || labels.fast,
    deep: modelLabel(run.settings.deep_model, labels) || labels.deep,
  };
}

/** Registry models usable in a role. */
export function modelsForRole(available: AvailableModel[], role: ModelRole): AvailableModel[] {
  return available.filter((m) => Array.isArray(m.roles) && m.roles.includes(role));
}

export const LabelsContext = createContext<Labels>(DEFAULT_LABELS);
export const useLabels = () => useContext(LabelsContext);

// ---------------------------------------------------------------- mixed-model fan-out

/** Label for an implementer model id: health `available_models` (matched on `model`), else the id's last path segment. */
export function implementerLabel(model: string, labels: Pick<Labels, "available">): string {
  const reg = labels.available.find((m) => !!m.model && m.model === model);
  if (reg?.label) return reg.label;
  const i = model.lastIndexOf("/");
  return i >= 0 ? model.slice(i + 1) : model;
}

/**
 * Shorten a set of labels for compact display: drop leading words they all share
 * ("NVIDIA Nemotron 3.5 Lightning" + "NVIDIA Nemotron Super" -> "3.5 Lightning", "Super"); otherwise drop a
 * leading "NVIDIA". Returns a map from original label to short label.
 */
export function compactLabels(all: string[]): Record<string, string> {
  const uniq = [...new Set(all)];
  const out: Record<string, string> = {};
  if (uniq.length === 0) return out;
  const words = uniq.map((l) => l.split(/\s+/));
  let k = 0;
  while (uniq.length > 1 && words.every((w) => w.length > k + 1 && w[k] === words[0][k])) k++;
  for (let i = 0; i < uniq.length; i++) {
    let short = words[i].slice(k).join(" ");
    if (k === 0) short = short.replace(/^NVIDIA\s+/, "");
    out[uniq[i]] = short || uniq[i];
  }
  return out;
}

export type ModelCount = { model: string; label: string; count: number };

/** Distinct models among executed implementations (in first-seen order). */
export function executedModels(run: Pick<Run, "implementations">): string[] {
  const seen: string[] = [];
  for (const i of run.implementations) if (i.status === "executed" && i.model && !seen.includes(i.model)) seen.push(i.model);
  return seen;
}

/** Per-cluster model breakdown, largest first. Labels are compacted across the whole run. */
export function clusterModelBreakdown(
  run: Pick<Run, "implementations" | "clusters">,
  labels: Pick<Labels, "available">,
): Record<string, ModelCount[]> {
  const models = executedModels(run);
  const full = Object.fromEntries(models.map((m) => [m, implementerLabel(m, labels)]));
  const short = compactLabels(Object.values(full));
  const byId = new Map(run.implementations.map((i) => [i.id, i]));
  const out: Record<string, ModelCount[]> = {};
  for (const c of run.clusters) {
    const counts = new Map<string, number>();
    for (const id of c.impl_ids) {
      const m = byId.get(id)?.model;
      if (m) counts.set(m, (counts.get(m) ?? 0) + 1);
    }
    out[c.id] = [...counts.entries()]
      .map(([model, count]) => ({ model, label: short[full[model] ?? model] ?? implementerLabel(model, labels), count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  }
  return out;
}

/** "Lightning 6 · Qwen 3" */
export function formatBreakdown(items: ModelCount[]): string {
  return items.map((i) => `${i.label} ${i.count}`).join(" · ");
}

/** Mixed-model summary for a run: null when every executed implementation came from one model. */
export function modelMix(
  run: Pick<Run, "implementations" | "clusters">,
  labels: Pick<Labels, "available">,
): { families: number; byCluster: Record<string, string>; byModel: Record<string, string> } | null {
  const models = executedModels(run);
  if (models.length < 2) return null;
  const breakdown = clusterModelBreakdown(run, labels);
  const short = compactLabels(models.map((m) => implementerLabel(m, labels)));
  return {
    families: models.length,
    byCluster: Object.fromEntries(Object.entries(breakdown).map(([cid, items]) => [cid, formatBreakdown(items)])),
    byModel: Object.fromEntries(models.map((m) => [m, short[implementerLabel(m, labels)]])),
  };
}
