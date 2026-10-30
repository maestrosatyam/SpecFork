import { describe, expect, it } from "vitest";
import {
  getRunToken,
  loadRunTokens,
  MAX_RUN_TOKENS,
  RUN_TOKENS_KEY,
  runTokenHeaders,
  saveRunToken,
  withRunToken,
} from "./runTokens";

function memStorage(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    raw: m,
  };
}

describe("run token storage", () => {
  it("round-trips a token under specfork.runTokens", () => {
    const s = memStorage();
    saveRunToken("r1", "t1", s);
    expect(JSON.parse(s.raw.get(RUN_TOKENS_KEY)!)).toEqual({ r1: "t1" });
    expect(getRunToken("r1", s)).toBe("t1");
    expect(getRunToken("nope", s)).toBeUndefined();
  });
  it("builds the X-Run-Token header only when a token is known", () => {
    const s = memStorage();
    saveRunToken("r1", "t1", s);
    expect(runTokenHeaders("r1", s)).toEqual({ "X-Run-Token": "t1" });
    expect(runTokenHeaders("r2", s)).toEqual({});
  });
  it("keeps only the newest MAX_RUN_TOKENS entries and refreshes re-saved ids", () => {
    let map: Record<string, string> = {};
    for (let i = 0; i < MAX_RUN_TOKENS + 5; i++) map = withRunToken(map, `run-${i}`, `tok-${i}`);
    const keys = Object.keys(map);
    expect(keys).toHaveLength(MAX_RUN_TOKENS);
    expect(keys[0]).toBe("run-5");
    expect(keys.at(-1)).toBe(`run-${MAX_RUN_TOKENS + 4}`);
    // Re-saving an old id moves it to the end, so it survives the next prune.
    map = withRunToken(map, "run-5", "new");
    expect(Object.keys(map).at(-1)).toBe("run-5");
    expect(map["run-5"]).toBe("new");
    map = withRunToken(map, "run-x", "x");
    expect(map["run-5"]).toBe("new");
    expect(map["run-6"]).toBeUndefined();
  });
  it("tolerates corrupt or non-object storage and drops non-string tokens", () => {
    expect(loadRunTokens(memStorage({ [RUN_TOKENS_KEY]: "{not json" }))).toEqual({});
    expect(loadRunTokens(memStorage({ [RUN_TOKENS_KEY]: "[1,2]" }))).toEqual({});
    expect(loadRunTokens(memStorage({ [RUN_TOKENS_KEY]: '{"a":"t","b":3,"c":""}' }))).toEqual({ a: "t" });
    expect(loadRunTokens(null)).toEqual({});
  });
  it("swallows storage write failures", () => {
    const s = { getItem: () => null, setItem: () => { throw new Error("quota"); } };
    expect(() => saveRunToken("r", "t", s)).not.toThrow();
  });
});
