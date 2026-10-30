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
