// API client. Same-origin `/api/...` in live mode; in-browser fake server in mock mode.
import type { Health, Preset, Run, RunSummary } from "./types";
import { MOCK_HEALTH, MOCK_PRESETS, MockHttpError, mockServer } from "./mock/mockApi";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

export const ACTIVE_STATUSES = new Set(["running", "resolving", "converging"]);

export interface Api {
  mode: "live" | "mock";
  health(): Promise<Health>;
  presets(): Promise<Preset[]>;
  listRuns(): Promise<RunSummary[]>;
  createRun(body: { spec: string; n_samples?: number; preset_id?: string }): Promise<{ id: string }>;
  getRun(id: string): Promise<Run>;
  /** Streams snapshots until the run leaves an active status. Returns an unsubscribe fn. */
  subscribe(id: string, onRun: (run: Run) => void, onEnd: () => void, onError?: (e: unknown) => void): () => void;
  postAnswers(id: string, answers: Record<string, string>): Promise<Run>;
  converge(id: string, n_samples?: number): Promise<Run>;
  /** Download URLs (blob URLs in mock mode). */
  testsUrl(run: Run): string;
  exportUrl(run: Run): string;
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "Can't reach the SpecFork server. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg) detail = String(body.detail[0].msg); // FastAPI 422
      else if (body?.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

// Runs are private by default: the server only lists recorded samples plus run ids this browser created.
const MY_RUNS_KEY = "specfork.myRuns";
function myRunIds(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(MY_RUNS_KEY) || "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, 20) : [];
  } catch {
    return [];
  }
}
function rememberRunId(id: string): void {
  try {
    localStorage.setItem(MY_RUNS_KEY, JSON.stringify([id, ...myRunIds().filter((x) => x !== id)].slice(0, 20)));
  } catch {
    /* storage unavailable */
  }
}

export const liveApi: Api = {
  mode: "live",
  health: () => http<Health>("/api/health"),
  presets: () => http<Preset[]>("/api/presets"),
  listRuns: () => http<RunSummary[]>(`/api/runs?ids=${encodeURIComponent(myRunIds().join(","))}`),
  createRun: async (body) => {
    const r = await http<{ id: string }>("/api/runs", { method: "POST", body: JSON.stringify(body) });
    rememberRunId(r.id);
    return r;
  },
  getRun: (id) => http<Run>(`/api/runs/${encodeURIComponent(id)}`),
  postAnswers: (id, answers) =>
    http<Run>(`/api/runs/${encodeURIComponent(id)}/answers`, { method: "POST", body: JSON.stringify({ answers }) }),
  converge: (id, n_samples) =>
    http<Run>(`/api/runs/${encodeURIComponent(id)}/converge`, {
      method: "POST",
      body: JSON.stringify(n_samples ? { n_samples } : {}),
    }),
  testsUrl: (run) => `/api/runs/${encodeURIComponent(run.id)}/tests.py`,
  exportUrl: (run) => `/api/runs/${encodeURIComponent(run.id)}/export.md`,
  subscribe(id, onRun, onEnd, onError) {
    let closed = false;
    let es: EventSource | null = null;
    let pollTimer: number | undefined;
    let ended = false;

    const finish = () => {
      if (ended) return;
      ended = true;
      onEnd();
    };

    const poll = async () => {
      if (closed) return;
      try {
        const run = await liveApi.getRun(id);
        if (closed) return;
        onRun(run);
        if (!ACTIVE_STATUSES.has(run.status)) return finish();
      } catch (e) {
        onError?.(e);
      }
      pollTimer = window.setTimeout(poll, 1500);
    };

    const startPolling = () => {
      es?.close();
      es = null;
      if (!closed && !ended && pollTimer === undefined) poll();
    };

    if (typeof EventSource === "undefined") {
      startPolling();
    } else {
      es = new EventSource(`/api/runs/${encodeURIComponent(id)}/events`);
      es.addEventListener("snapshot", (ev) => {
        try {
          const run = JSON.parse((ev as MessageEvent).data) as Run;
          onRun(run);
          if (!ACTIVE_STATUSES.has(run.status)) {
            // Server will also send `end`; close proactively so the browser doesn't auto-reconnect.
            es?.close();
            finish();
          }
        } catch (e) {
          onError?.(e);
        }
      });
      es.addEventListener("end", () => {
        es?.close();
        es = null;
        // One last GET so we have the final state even if the last snapshot was throttled away.
        liveApi
          .getRun(id)
          .then((run) => !closed && onRun(run))
          .catch(() => undefined)
          .finally(finish);
      });
      es.onerror = () => {
        if (ended || closed) return;
        // SSE broken (proxy buffering, network blip, or not supported): fall back to polling.
        startPolling();
      };
    }

    return () => {
      closed = true;
      es?.close();
      if (pollTimer !== undefined) window.clearTimeout(pollTimer);
    };
  },
};

function wrapMock<T>(fn: () => T): Promise<T> {
  return new Promise((resolve, reject) => {
    window.setTimeout(() => {
      try {
        resolve(fn());
      } catch (e) {
        if (e instanceof MockHttpError) reject(new ApiError(e.status, e.detail));
        else reject(e);
      }
    }, 120);
  });
}

const blobCache = new Map<string, string>();
function blobUrl(key: string, content: string, type: string): string {
  const k = `${key}:${content.length}`;
  if (!blobCache.has(k)) blobCache.set(k, URL.createObjectURL(new Blob([content], { type })));
  return blobCache.get(k)!;
}

function exportMarkdown(run: Run): string {
  const r = run.resolution;
  if (!r) return `# SpecFork run ${run.id}\n\nNot resolved yet.\n`;
  return [
    `# SpecFork: clarified spec`,
    ``,
    `**Original spec:** ${run.spec}`,
    ``,
    `## Clarified spec`,
    ``,
    r.clarified_spec,
    ``,
    `## Decisions`,
    ``,
    ...r.decisions.map((d) => `- ${d}`),
    ``,
    `## tests.py`,
    ``,
    "```python",
    r.tests_code,
    "```",
    ``,
    `## Reference implementation`,
    ``,
    "```python",
    r.reference_code,
    "```",
    ``,
  ].join("\n");
}

export const mockApi: Api = {
  mode: "mock",
  health: () => wrapMock(() => MOCK_HEALTH),
  presets: () => wrapMock(() => MOCK_PRESETS),
  listRuns: () => wrapMock(() => mockServer().list()),
  createRun: (body) =>
    wrapMock(() => {
      const spec = body.spec.trim();
      if (!spec) throw new MockHttpError(422, "Spec is empty.");
      return { id: mockServer().create(spec, body.n_samples ?? 24) };
    }),
  getRun: (id) => wrapMock(() => JSON.parse(JSON.stringify(mockServer().get(id))) as Run),
  postAnswers: (id, answers) => wrapMock(() => mockServer().answers(id, answers)),
  converge: (id, n) => wrapMock(() => mockServer().converge(id, n)),
  subscribe: (id, onRun, onEnd) => mockServer().subscribe(id, onRun, onEnd),
  testsUrl: (run) => blobUrl(`${run.id}-tests`, run.resolution?.tests_code ?? "", "text/x-python"),
  exportUrl: (run) => blobUrl(`${run.id}-export`, exportMarkdown(run), "text/markdown"),
};

export function wantsMock(): boolean {
  const q = new URLSearchParams(window.location.search);
  return q.get("mock") === "1" || q.get("mock") === "true";
}

/** Decide live vs mock: `?mock=1` forces mock; otherwise probe /api/health (2.5s timeout). */
export async function detectApi(): Promise<{ api: Api; health: Health | null; reason?: string }> {
  if (wantsMock()) return { api: mockApi, health: MOCK_HEALTH, reason: "forced" };
  const ctl = new AbortController();
  const timer = window.setTimeout(() => ctl.abort(), 2500);
  try {
    const res = await fetch("/api/health", { signal: ctl.signal });
    const ct = res.headers.get("content-type") ?? "";
    if (!res.ok || !ct.includes("json")) throw new Error(`health ${res.status}`);
    const health = (await res.json()) as Health;
    return { api: liveApi, health };
  } catch {
    return { api: mockApi, health: MOCK_HEALTH, reason: "unreachable" };
  } finally {
    window.clearTimeout(timer);
  }
}
