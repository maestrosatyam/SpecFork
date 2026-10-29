import { describe, expect, it } from "vitest";
import { formatCall, formatCost, formatDuration, formatPct, formatTokens, isErrorRepr, pyRepr, shortModel } from "./format";

describe("formatCost", () => {
  it("uses 4 decimals for typical run totals", () => {
    expect(formatCost(0.0042)).toBe("$0.0042");
    expect(formatCost(0.02138)).toBe("$0.0214");
  });
  it("keeps tiny per-call costs readable", () => {
    expect(formatCost(0.0000861)).toBe("$0.000086");
  });
  it("handles zero, null and dollars", () => {
    expect(formatCost(0)).toBe("$0.0000");
    expect(formatCost(undefined)).toBe("$0.0000");
    expect(formatCost(1.5)).toBe("$1.50");
  });
});

describe("formatTokens / formatPct / formatDuration", () => {
  it("abbreviates tokens", () => {
    expect(formatTokens(950)).toBe("950");
    expect(formatTokens(41234)).toBe("41.2k");
    expect(formatTokens(12000)).toBe("12k");
    expect(formatTokens(1_250_000)).toBe("1.25M");
  });
  it("rounds percentages", () => {
    expect(formatPct(0.375)).toBe("38%");
    expect(formatPct(0.9167)).toBe("92%");
    expect(formatPct(undefined)).toBe("–");
  });
  it("formats durations", () => {
    expect(formatDuration(0.842)).toBe("0.84s");
    expect(formatDuration(12.34)).toBe("12.3s");
    expect(formatDuration(125)).toBe("2m 05s");
  });
});

describe("python rendering", () => {
  it("renders python literals", () => {
    expect(pyRepr([1, "a'b", null, true])).toBe("[1, 'a\\'b', None, True]");
    expect(pyRepr({ k: false })).toBe("{'k': False}");
  });
  it("formats calls positionally with float-aware params", () => {
    const params = [
      { name: "total", type: "float" },
      { name: "n", type: "int" },
    ];
    expect(formatCall("split_bill", { total: 100, n: 3 }, params)).toBe("split_bill(100.0, 3)");
    expect(formatCall("split_bill", { n: 3, total: 0.01 }, params)).toBe("split_bill(0.01, 3)");
  });
  it("falls back to keyword form without a matching signature", () => {
    expect(formatCall("f", { x: "hi", y: [1, 2] })).toBe("f(x='hi', y=[1, 2])");
    expect(formatCall(undefined, { z: 1 }, [{ name: "a", type: "int" }])).toBe("fn(z=1)");
  });
  it("uses keywords after a skipped optional param", () => {
    const params = [
      { name: "a", type: "int" },
      { name: "b", type: "int" },
      { name: "c", type: "str" },
    ];
    expect(formatCall("g", { a: 1, c: "x" }, params)).toBe("g(1, c='x')");
  });
  it("detects exception reprs", () => {
    expect(isErrorRepr("ValueError")).toBe(true);
    expect(isErrorRepr("Timeout")).toBe(true);
    expect(isErrorRepr("[33.33]")).toBe(false);
    expect(isErrorRepr("'Error'")).toBe(false);
  });
  it("shortens model ids", () => {
    expect(shortModel("nvidia/Nemotron-3-Ultra-550b-a55b")).toBe("Nemotron-3-Ultra-550b-a55b");
  });
});
