// Per-run capability tokens (returned by POST /api/runs). Only the browser that started a run can answer it.
// Stored as a {runId: token} map in localStorage, newest last, capped at MAX_RUN_TOKENS entries.

export const RUN_TOKENS_KEY = "specfork.runTokens";
export const MAX_RUN_TOKENS = 50;

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function defaultStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function loadRunTokens(storage: StorageLike | null = defaultStorage()): Record<string, string> {
  if (!storage) return {};
  try {
    const v = JSON.parse(storage.getItem(RUN_TOKENS_KEY) || "{}");
    if (!v || typeof v !== "object" || Array.isArray(v)) return {};
    const out: Record<string, string> = {};
    for (const [k, t] of Object.entries(v)) if (typeof t === "string" && t) out[k] = t;
    return out;
  } catch {
    return {};
  }
}

/** Pure: add/refresh `id` as the newest entry and keep only the last `max`. */
export function withRunToken(
  map: Record<string, string>,
  id: string,
  token: string,
  max = MAX_RUN_TOKENS,
): Record<string, string> {
  const entries = Object.entries(map).filter(([k]) => k !== id);
  entries.push([id, token]);
  return Object.fromEntries(entries.slice(Math.max(0, entries.length - max)));
}

export function saveRunToken(id: string, token: string, storage: StorageLike | null = defaultStorage()): void {
  if (!storage || !id || !token) return;
  try {
    storage.setItem(RUN_TOKENS_KEY, JSON.stringify(withRunToken(loadRunTokens(storage), id, token)));
  } catch {
    /* storage full or unavailable */
  }
}

export function getRunToken(id: string, storage: StorageLike | null = defaultStorage()): string | undefined {
  return loadRunTokens(storage)[id];
}

/** Headers for owner-only endpoints (answers, converge). */
export function runTokenHeaders(id: string, storage: StorageLike | null = defaultStorage()): Record<string, string> {
  const t = getRunToken(id, storage);
  return t ? { "X-Run-Token": t } : {};
}

export const NOT_OWNER_MSG = "Only the browser that started this run can answer it — fork the spec to run your own.";
