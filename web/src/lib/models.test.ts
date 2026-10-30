import { describe, expect, it } from "vitest";
import { howSteps } from "../components/HowItWorks";
import { MOCK_HEALTH } from "../mock/mockApi";
import type { Health } from "../types";
import {
  commonFamily,
  DEFAULT_DEEP_LABEL,
  DEFAULT_FAST_LABEL,
  DEFAULT_PROVIDER_LABEL,
  labelsFromHealth,
  modelLabel,
  modelsForRole,
  implementerLabel,
  compactLabels,
  executedModels,
  modelMix,
  clusterModelBreakdown,
  formatBreakdown,
} from "./models";

const health: Health = {
  ok: true,
  llm_configured: true,
  version: "x",
  models: { fast: "acme/fast-1", deep: "acme/deep-9" },
  provider_label: "Acme Cloud",
  model_labels: { fast: "Acme Coder Mini", deep: "Acme Coder Max" },
  available_models: [
    { key: "mini", label: "Acme Coder Mini", roles: ["fast"] },
    { key: "max", label: "Acme Coder Max", roles: ["deep"] },
    { key: "mid", label: "Acme Coder Mid", roles: ["fast", "deep"], model: "acme/mid-3" },
  ],
};

describe("labels from health", () => {
  it("falls back to the NVIDIA / Nebius defaults without health", () => {
    const l = labelsFromHealth(null);
    expect(l.fast).toBe(DEFAULT_FAST_LABEL);
    expect(l.deep).toBe(DEFAULT_DEEP_LABEL);
    expect(l.provider).toBe(DEFAULT_PROVIDER_LABEL);
    expect(l.family).toBe("NVIDIA Nemotron");
  });
  it("uses health labels when present", () => {
    const l = labelsFromHealth(health);
    expect([l.fast, l.deep, l.provider, l.family]).toEqual(["Acme Coder Mini", "Acme Coder Max", "Acme Cloud", "Acme Coder"]);
  });
  it("mock health carries NVIDIA / Nebius names", () => {
    const l = labelsFromHealth(MOCK_HEALTH);
    expect(l.family).toBe("NVIDIA Nemotron");
    expect(l.provider).toBe("Nebius Token Factory");
  });
  it("commonFamily strips version tokens and handles unrelated names", () => {
    expect(commonFamily("NVIDIA Nemotron 3 Super", "NVIDIA Nemotron 3 Ultra")).toBe("NVIDIA Nemotron");
    expect(commonFamily("Foo", "Bar")).toBe("Foo and Bar");
    expect(commonFamily("Same", "Same")).toBe("Same");
  });
  it("maps model ids and registry keys to labels", () => {
    const l = labelsFromHealth(health);
    expect(modelLabel("acme/fast-1", l)).toBe("Acme Coder Mini");
    expect(modelLabel("acme/deep-9", l)).toBe("Acme Coder Max");
    expect(modelLabel("mid", l)).toBe("Acme Coder Mid");
    expect(modelLabel("acme/mid-3", l)).toBe("Acme Coder Mid");
    expect(modelLabel("vendor/other-model", l)).toBe("other-model");
  });
  it("filters registry models by role", () => {
    const l = labelsFromHealth(health);
    expect(modelsForRole(l.available, "fast").map((m) => m.key)).toEqual(["mini", "mid"]);
    expect(modelsForRole(l.available, "deep").map((m) => m.key)).toEqual(["max", "mid"]);
  });
});

describe("how it works copy", () => {
  it("credits framing + fan-out + re-fork to the fast model and questions/spec to the deep model", () => {
    const [fork, , ask, lock] = howSteps({ fast: "FAST", deep: "DEEP" });
    expect(fork.body).toMatch(/^FAST frames/);
    expect(fork.body).not.toContain("DEEP");
    expect(ask.body).toContain("DEEP turns it");
    expect(ask.body).toContain("silent assumptions");
    expect(lock.body).toMatch(/^DEEP writes your answers into a clarified spec/);
    expect(lock.body).toContain("on FAST");
  });
});

describe("mixed-model fan-out breakdown", () => {
  const available = [
    { key: "lightning", label: "NVIDIA Nemotron 3.5 Lightning", roles: ["fast" as const], model: "nvidia/Nemotron-3_5-Lightning" },
    { key: "super", label: "NVIDIA Nemotron 3 Super", roles: ["fast" as const], model: "nvidia/Nemotron-3-Super-120b-a12b" },
  ];
  const impl = (id: string, model: string, status: "executed" | "rejected" = "executed") => ({ id, index: 0, model, status });
  const L = "nvidia/Nemotron-3_5-Lightning";
  const S = "nvidia/Nemotron-3-Super-120b-a12b";
  const Q = "Qwen/Qwen3-Coder-480B-A35B-Instruct";
  const cluster = (id: string, impl_ids: string[]) => ({
    id,
    label: id,
    impl_ids,
    size: impl_ids.length,
    share: 0,
    representative_impl_id: impl_ids[0],
    kind: "behavior" as const,
  });

  it("labels implementers from available_models, else the id's last segment", () => {
    expect(implementerLabel(L, { available })).toBe("NVIDIA Nemotron 3.5 Lightning");
    expect(implementerLabel(Q, { available })).toBe("Qwen3-Coder-480B-A35B-Instruct");
    expect(implementerLabel("plain-model", { available: [] })).toBe("plain-model");
  });

  it("compacts labels by their shared leading words", () => {
    expect(compactLabels(["NVIDIA Nemotron 3.5 Lightning", "NVIDIA Nemotron 3 Super"])).toEqual({
      "NVIDIA Nemotron 3.5 Lightning": "3.5 Lightning",
      "NVIDIA Nemotron 3 Super": "3 Super",
    });
    expect(compactLabels(["NVIDIA Nemotron 3.5 Lightning", "Qwen3-Coder"])).toEqual({
      "NVIDIA Nemotron 3.5 Lightning": "Nemotron 3.5 Lightning",
      "Qwen3-Coder": "Qwen3-Coder",
    });
  });

  it("returns null for single-model runs and ignores non-executed impls", () => {
    const run = { implementations: [impl("a", L), impl("b", L), impl("c", S, "rejected")], clusters: [cluster("cA", ["a", "b"])] };
    expect(executedModels(run)).toEqual([L]);
    expect(modelMix(run, { available })).toBeNull();
  });

  it("breaks each cluster down per model, largest first", () => {
    const run = {
      implementations: [impl("a", L), impl("b", Q), impl("c", Q), impl("d", L), impl("e", L)],
      clusters: [cluster("cA", ["a", "b", "c"]), cluster("cB", ["d", "e"])],
    };
    const bd = clusterModelBreakdown(run, { available });
    expect(bd.cA.map((x) => [x.label, x.count])).toEqual([
      ["Qwen3-Coder-480B-A35B-Instruct", 2],
      ["Nemotron 3.5 Lightning", 1],
    ]);
    expect(formatBreakdown(bd.cB)).toBe("Nemotron 3.5 Lightning 2");
    const mix = modelMix(run, { available })!;
    expect(mix.families).toBe(2);
    expect(mix.byCluster.cA).toBe("Qwen3-Coder-480B-A35B-Instruct 2 · Nemotron 3.5 Lightning 1");
  });
});
