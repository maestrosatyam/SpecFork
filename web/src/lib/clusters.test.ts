import { describe, expect, it } from "vitest";
import { buildBillRun } from "../mock/billFixture";
import {
  activeClusterIds,
  allAmbiguitiesAnswered,
  clusterStyles,
  CRASH_COLOR,
  optionImplCount,
  stageIndex,
} from "./clusters";

const run = buildBillRun({ id: "t", n: 24, createdAt: 1_700_000_000 });

describe("activeClusterIds", () => {
  it("returns null when nothing is answered", () => {
    expect(activeClusterIds(run.questions, {})).toBeNull();
  });
  it("narrows to the chosen option's clusters", () => {
    expect([...activeClusterIds(run.questions, { q1: "q1_first" })!].sort()).toEqual(["cA", "cD"]);
  });
  it("intersects across answered questions", () => {
    expect([...activeClusterIds(run.questions, { q1: "q1_first", q2: "q2_raise" })!]).toEqual(["cA"]);
    expect([...activeClusterIds(run.questions, { q1: "q1_down", q2: "q2_empty" })!]).toEqual([]);
  });
  it("ignores likely_bug questions and unknown options", () => {
    expect(activeClusterIds(run.questions, { q3: "q3_crash" })).toBeNull();
    expect(activeClusterIds(run.questions, { q1: "nope" })).toBeNull();
  });
});

describe("answers + counts", () => {
  it("requires every ambiguity question", () => {
    expect(allAmbiguitiesAnswered(run.questions, { q1: "q1_first" })).toBe(false);
    expect(allAmbiguitiesAnswered(run.questions, { q1: "q1_first", q2: "q2_empty" })).toBe(true);
    expect(allAmbiguitiesAnswered([], {})).toBe(false);
  });
  it("counts implementations behind an option", () => {
    expect(optionImplCount(run.clusters, ["cA", "cD"])).toBe(12);
    expect(optionImplCount(run.clusters, ["cB"])).toBe(6);
  });
});

describe("clusterStyles", () => {
  it("gives behaviour clusters distinct colours and crash clusters the crash style", () => {
    const s = clusterStyles(run.clusters);
    const behaviour = run.clusters.filter((c) => c.kind === "behavior").map((c) => s[c.id].color);
    expect(new Set(behaviour).size).toBe(behaviour.length);
    expect(s.cE).toEqual({ color: CRASH_COLOR, crash: true, label: "E" });
  });
});

describe("fixture sanity", () => {
  it("matches the scripted 24-sample story", () => {
    expect(run.implementations).toHaveLength(24);
    expect(run.clusters.map((c) => [c.label, c.size])).toEqual([
      ["A", 9],
      ["B", 6],
      ["C", 4],
      ["D", 3],
      ["E", 1],
    ]);
    expect(stageIndex("cluster")).toBe(3);
    expect(stageIndex("done")).toBe(5);
  });
});
