import { describe, expect, it } from "vitest";
import { buildBillRun, buildResolution } from "../mock/billFixture";
import {
  activeClusterIds,
  answeredCount,
  answersFromRun,
  buildAnswersBody,
  ignoresClusters,
  isAnswered,
  OTHER_MAX,
  allAmbiguitiesAnswered,
  allAnswered,
  answerableQuestions,
  optionCompatible,
  optionCount,
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

describe("assumptions + compatibility", () => {
  const a0 = run.questions.find((q) => q.id === "a0")!;
  const q2 = run.questions.find((q) => q.id === "q2")!;
  it("ignores alternative options when filtering clusters", () => {
    expect(activeClusterIds(run.questions, { a0: "a0alt" })).toBeNull();
    expect([...activeClusterIds(run.questions, { q1: "q1_first", a0: "a0alt" })!].sort()).toEqual(["cA", "cD"]);
  });
  it("keeping an assumption constrains to the consensus clusters", () => {
    expect([...activeClusterIds(run.questions, { a0: "a0keep" })!].sort()).toEqual(["cA", "cB", "cC", "cD"]);
  });
  it("flags options no implementation combines with the other answers", () => {
    const empty = q2.options.find((o) => o.id === "q2_empty")!;
    const raise = q2.options.find((o) => o.id === "q2_raise")!;
    expect(optionCompatible(run.questions, { q1: "q1_down" }, q2, empty)).toBe(false);
    expect(optionCompatible(run.questions, { q1: "q1_down" }, q2, raise)).toBe(true);
    expect(optionCompatible(run.questions, {}, q2, empty)).toBe(true);
    // the question's own answer doesn't count against its options
    expect(optionCompatible(run.questions, { q2: "q2_raise" }, q2, empty)).toBe(true);
  });
  it("treats alternatives as always compatible", () => {
    const alt = a0.options.find((o) => o.is_alternative)!;
    expect(optionCompatible(run.questions, { q1: "q1_down", q2: "q2_empty" }, a0, alt)).toBe(true);
  });
});

describe("answers + counts", () => {
  it("requires every ambiguity and assumption question", () => {
    expect(answerableQuestions(run.questions).map((q) => q.id)).toEqual(["q1", "q2", "a0"]);
    expect(allAnswered(run.questions, { q1: "q1_first", q2: "q2_empty" })).toBe(false);
    expect(allAnswered(run.questions, { q1: "q1_first", q2: "q2_empty", a0: "a0alt" })).toBe(true);
    expect(allAmbiguitiesAnswered(run.questions, { q1: "q1_first", q2: "q2_empty", a0: "a0keep" })).toBe(true);
    expect(allAnswered([], {})).toBe(false);
  });
  it("prefers the server's impl_count", () => {
    const q1 = run.questions.find((q) => q.id === "q1")!;
    expect(optionCount(run.clusters, { ...q1.options[0], impl_count: 99 })).toBe(99);
    expect(optionCount(run.clusters, { ...q1.options[0], impl_count: undefined })).toBe(12);
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

describe("mock resolution", () => {
  it("unlocks the affected cases when an assumption is overridden", () => {
    const keep = buildResolution(run, { q1: "q1_first", q2: "q2_raise", a0: "a0keep" }).resolution;
    const alt = buildResolution(run, { q1: "q1_first", q2: "q2_raise", a0: "a0alt" }).resolution;
    expect(keep.unlocked_input_ids).toEqual([]);
    expect(alt.unlocked_input_ids).toEqual(["in9"]);
    expect(alt.locked_cases.map((c) => c.input_id)).not.toContain("in9");
    expect(alt.reference_code).toContain("total < 0");
    expect(keep.agreement_before).toBeCloseTo(9 / 24);
  });
});

describe("free-text Other answers", () => {
  it("counts a question answered by an option OR by other text of at least 3 chars", () => {
    expect(answeredCount(run.questions, {}, {})).toBe(0);
    expect(answeredCount(run.questions, { q1: "q1_first" }, {})).toBe(1);
    expect(answeredCount(run.questions, {}, { q1: "split it by seniority" })).toBe(1);
    expect(answeredCount(run.questions, {}, { q1: "ab" })).toBe(0); // too short
    expect(answeredCount(run.questions, {}, { q1: "   ab   " })).toBe(0); // whitespace doesn't count
    expect(answeredCount(run.questions, {}, { q1: "" })).toBe(0); // Other selected, nothing typed yet
    expect(answeredCount(run.questions, { q1: "q1_first" }, { q2: "return None" })).toBe(2);
    // likely_bug questions never count, with or without text
    expect(answeredCount(run.questions, { q3: "q3_ok" }, { q3: "whatever" })).toBe(0);
  });
  it("isAnswered ignores unknown option ids", () => {
    const q1 = run.questions.find((q) => q.id === "q1")!;
    expect(isAnswered(q1, { q1: "nope" })).toBe(false);
    expect(isAnswered(q1, { q1: "nope" }, { q1: "abc" })).toBe(true);
  });
  it("allAnswered accepts a mix of options and other text", () => {
    expect(allAnswered(run.questions, { q1: "q1_first", q2: "q2_raise" }, { a0: "no" })).toBe(false);
    expect(allAnswered(run.questions, { q1: "q1_first", q2: "q2_raise" }, { a0: "refunds raise ValueError" })).toBe(true);
    expect(allAnswered(run.questions, {}, { q1: "abc", q2: "def", a0: "ghi" })).toBe(true);
  });
  it("buildAnswersBody sends exactly one of option/other per question, trimmed and capped", () => {
    const long = "x".repeat(400);
    const body = buildAnswersBody(
      run.questions,
      { q1: "q1_first", q2: "q2_raise", q3: "q3_ok" },
      { q1: "ignored because an option is selected", a0: `  ${long}  `, q2: "" },
    );
    expect(body.answers).toEqual({ q1: "q1_first", q2: "q2_raise" });
    expect(Object.keys(body.other)).toEqual(["a0"]);
    expect(body.other.a0).toHaveLength(OTHER_MAX);
    expect(buildAnswersBody(run.questions, {}, { q1: "  a b  ", q2: "ok" })).toEqual({
      answers: {},
      other: { q1: "a b" },
    });
  });
});

describe("cluster filtering ignores custom and alternative options", () => {
  const withCustom = structuredClone(run);
  const q1 = withCustom.questions.find((q) => q.id === "q1")!;
  q1.options.push({ id: "q1other", label: "my rule", is_custom: true, cluster_ids: ["cB"], impl_count: 0, examples: [] });
  it("a selected custom option does not constrain highlighting", () => {
    expect(ignoresClusters(q1.options.at(-1)!)).toBe(true);
    expect(activeClusterIds(withCustom.questions, { q1: "q1other" })).toBeNull();
    expect([...activeClusterIds(withCustom.questions, { q1: "q1other", q2: "q2_empty" })!]).toEqual(["cD"]);
  });
  it("custom and alternative options together still leave everything highlighted", () => {
    expect(activeClusterIds(withCustom.questions, { q1: "q1other", a0: "a0alt" })).toBeNull();
  });
  it("custom options are always compatible and count zero implementations", () => {
    const custom = q1.options.at(-1)!;
    expect(optionCompatible(withCustom.questions, { q2: "q2_empty" }, q1, custom)).toBe(true);
    expect(optionCount(withCustom.clusters, { ...custom, impl_count: undefined })).toBe(0);
  });
  it("answersFromRun picks up the server-selected custom option", () => {
    const r = structuredClone(withCustom);
    r.questions.find((q) => q.id === "q1")!.answer_option_id = "q1other";
    expect(answersFromRun(r).q1).toBe("q1other");
    expect(allAnswered(r.questions, { ...answersFromRun(r), q2: "q2_raise", a0: "a0keep" })).toBe(true);
  });
});

describe("mock resolution with free-text answers", () => {
  it("writes a custom implementation with the deep model and leaves a case open", () => {
    const { resolution, customImpl } = buildResolution(run, { q2: "q2_raise", a0: "a0keep" }, { q1: "the host pays the extra cent" });
    expect(customImpl?.id).toBe(resolution.custom_impl_id);
    expect(customImpl?.model).toBe(run.settings.deep_model);
    expect(customImpl?.status).toBe("executed");
    expect(resolution.open_input_ids).toEqual(["in7"]);
    expect(resolution.locked_cases.map((c) => c.input_id)).not.toContain("in7");
    expect(resolution.clarified_spec).toContain("the host pays the extra cent");
  });
  it("has no custom implementation or open cases without free text", () => {
    const { resolution, customImpl } = buildResolution(run, { q1: "q1_first", q2: "q2_raise", a0: "a0keep" });
    expect(customImpl).toBeUndefined();
    expect(resolution.custom_impl_id).toBeUndefined();
    expect(resolution.open_input_ids).toEqual([]);
  });
});
