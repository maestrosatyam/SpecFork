import { describe, expect, it } from "vitest";
import { addedWordCount, wordDiff } from "./diff";

const join = (segs: { type: string; text: string }[], skip: string) =>
  segs.filter((s) => s.type !== skip).map((s) => s.text).join("");

describe("wordDiff", () => {
  it("marks appended clarifications as additions", () => {
    const before = "Split a bill evenly among N people, rounding to cents.";
    const after = "Split a bill evenly among N people, rounding to cents. Leftover cents go to the first people.";
    const segs = wordDiff(before, after);
    expect(segs[0]).toEqual({ type: "same", text: before });
    expect(segs.filter((s) => s.type === "add").map((s) => s.text.trim())).toEqual([
      "Leftover cents go to the first people.",
    ]);
    expect(addedWordCount(segs)).toBe(7);
  });
  it("reconstructs both sides exactly", () => {
    const before = "Return the number of business days between two dates.";
    const after = "Return the number of weekdays (Mon–Fri) between two dates, excluding the start date.";
    const segs = wordDiff(before, after);
    expect(join(segs, "del")).toBe(after);
    expect(join(segs, "add").replace(/\s+/g, " ")).toBe(before);
  });
  it("detects in-place replacements", () => {
    const segs = wordDiff("raise an error", "raise ValueError");
    expect(segs.some((s) => s.type === "del" && s.text.includes("error"))).toBe(true);
    expect(segs.some((s) => s.type === "add" && s.text.includes("ValueError"))).toBe(true);
  });
  it("handles empty input", () => {
    expect(wordDiff("", "")).toEqual([]);
    expect(wordDiff("", "new text")).toEqual([{ type: "add", text: "new text" }]);
  });
});
