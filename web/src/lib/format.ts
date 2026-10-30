// Pure formatting helpers (unit-tested in format.test.ts).

/**
 * "$0.0042" style. ≥ $1: 2 decimals; ≥ $0.001: 4 decimals; smaller: 6 decimals (so per-call costs like
 * $0.000086 stay readable instead of rounding to $0.0001).
 */
export function formatCost(usd: number | undefined | null): string {
  if (usd == null || !Number.isFinite(usd) || usd === 0) return "$0.0000";
  const a = Math.abs(usd);
  if (a >= 1) return `$${usd.toFixed(2)}`;
  if (a >= 0.001) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(6)}`;
}

/** 950 -> "950", 41234 -> "41.2k", 1_250_000 -> "1.25M" */
export function formatTokens(n: number | undefined | null): string {
  if (n == null || !Number.isFinite(n)) return "0";
  if (n < 1000) return String(Math.round(n));
  if (n < 1_000_000) {
    const k = n / 1000;
    return `${k >= 100 ? Math.round(k) : k.toFixed(1).replace(/\.0$/, "")}k`;
  }
  return `${(n / 1_000_000).toFixed(2).replace(/\.?0+$/, "")}M`;
}

/** 0.375 -> "38%" */
export function formatPct(share: number | undefined | null, digits = 0): string {
  if (share == null || !Number.isFinite(share)) return "–";
  return `${(share * 100).toFixed(digits)}%`;
}

/** Seconds to "0.84s", "12.3s", "2m 05s". */
export function formatDuration(s: number | undefined | null): string {
  if (s == null || !Number.isFinite(s)) return "–";
  if (s < 10) return `${s.toFixed(2)}s`;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s - m * 60);
  return `${m}m ${String(rest).padStart(2, "0")}s`;
}

/** Accepts unix seconds or milliseconds. */
export function toDate(ts: number): Date {
  return new Date(ts > 1e12 ? ts : ts * 1000);
}

export function formatDate(ts: number): string {
  return toDate(ts).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Render a JSON-ish value as a Python literal (True/False/None, single-quoted strings). */
export function pyRepr(v: unknown): string {
  if (v === null || v === undefined) return "None";
  if (v === true) return "True";
  if (v === false) return "False";
  if (typeof v === "number") {
    if (Number.isNaN(v)) return "float('nan')";
    if (!Number.isFinite(v)) return v > 0 ? "float('inf')" : "-float('inf')";
    return String(v);
  }
  if (typeof v === "string") {
    return `'${v.replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/\n/g, "\\n")}'`;
  }
  if (Array.isArray(v)) return `[${v.map(pyRepr).join(", ")}]`;
  if (typeof v === "object") {
    const entries = Object.entries(v as Record<string, unknown>).map(([k, val]) => `${pyRepr(k)}: ${pyRepr(val)}`);
    return `{${entries.join(", ")}}`;
  }
  return String(v);
}

/** Python repr for a value whose declared type is known (JSON loses the 100.0 vs 100 distinction). */
export function pyReprTyped(v: unknown, type?: string): string {
  if (typeof v === "number" && Number.isInteger(v) && type && /^(float|Optional\[float\]|float \| None)$/.test(type.trim()))
    return `${v}.0`;
  return pyRepr(v);
}

/**
 * Render a call. With the signature's params, uses positional args in declared order — split_bill(100.0, 3) —
 * and float-aware reprs. Without (or when args don't match the params), falls back to keyword form.
 */
export function formatCall(
  fnName: string | undefined,
  args: Record<string, unknown>,
  params?: { name: string; type: string }[],
): string {
  const keys = Object.keys(args);
  if (params && params.length && keys.every((k) => params.some((p) => p.name === k))) {
    const parts: string[] = [];
    let skipped = false;
    for (const p of params) {
      if (!(p.name in args)) {
        skipped = true;
        continue;
      }
      parts.push(skipped ? `${p.name}=${pyReprTyped(args[p.name], p.type)}` : pyReprTyped(args[p.name], p.type));
    }
    return `${fnName || "fn"}(${parts.join(", ")})`;
  }
  const parts = Object.entries(args).map(([k, v]) => `${k}=${pyRepr(v)}`);
  return `${fnName || "fn"}(${parts.join(", ")})`;
}

export function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, Math.max(0, max - 1)).trimEnd() + "…";
}

/** Short model name for tables: "nvidia/Nemotron-3-Ultra-550b-a55b" -> "Nemotron-3-Ultra-550b-a55b". */
export function shortModel(model: string): string {
  const i = model.lastIndexOf("/");
  return i >= 0 ? model.slice(i + 1) : model;
}

/** Friendly model family label used in badges. */
export function modelFamily(model: string): string {
  const m = model.toLowerCase();
  if (m.includes("ultra")) return "Nemotron 3 Ultra";
  if (m.includes("lightning")) return "Nemotron 3.5 Lightning";
  if (m.includes("super")) return "Nemotron Super";
  if (m.includes("nano")) return "Nemotron Nano";
  return shortModel(model);
}

const LEGACY_EXC = /^[A-Z]\w*(Error|Exception|Exit|Interrupt|Warning)$|^Timeout$/;

/**
 * How to show an outcome repr. Backends emit "raises" (any exception) or, with exception types on,
 * "raises:ValueError". Older runs/fixtures use the bare type ("ValueError").
 */
export function describeRepr(repr: string): { raises: boolean; type?: string; text: string } {
  const r = (repr ?? "").trim();
  if (r === "raises") return { raises: true, text: "raises" };
  const m = r.match(/^raises:\s*([\w.]+)$/);
  if (m) return { raises: true, type: m[1], text: `raises ${m[1]}` };
  if (LEGACY_EXC.test(r)) return { raises: true, type: r, text: `raises ${r}` };
  return { raises: false, text: repr };
}

/** "raises", "raises:ValueError", "ValueError", "Timeout" -> true. Used to style raised exceptions differently from values. */
export function isErrorRepr(repr: string): boolean {
  return describeRepr(repr).raises;
}
