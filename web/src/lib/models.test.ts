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
