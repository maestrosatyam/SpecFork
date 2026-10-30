// Realistic fixture: the "split a restaurant bill" run. Used by mock mode (?mock=1 or backend unreachable).
// buildBillRun() produces a *complete* run (awaiting_answers); mockApi.ts replays it as a live progression.
import type {
  CallRecord,
  Cluster,
  Implementation,
  Outcome,
  ProbeInput,
  Question,
  Resolution,
  Run,
} from "../types";

export const FAST_MODEL = "nvidia/Nemotron-3_5-Lightning";
export const DEEP_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b";
/** Extra registry model so mock mode shows the Advanced model selects. */
export const SUPER_MODEL = "nvidia/Nemotron-3-Super-120b-a12b";
// Display labels the mock /api/health returns (the live backend sends its own).
export const FAST_LABEL = "NVIDIA Nemotron 3.5 Lightning";
export const DEEP_LABEL = "NVIDIA Nemotron 3 Ultra";
export const SUPER_LABEL = "NVIDIA Nemotron 3 Super";
export const PROVIDER_LABEL = "Nebius Token Factory";
export const BILL_SPEC = "Split a restaurant bill evenly among N people, rounding to cents.";
export const SAMPLE_RUN_ID = "sample-bill-split";

const PRICES: Record<string, [number, number]> = {
  [FAST_MODEL]: [0.06, 0.24],
  [DEEP_MODEL]: [1.0, 3.0],
  [SUPER_MODEL]: [0.3, 0.9],
};

export function cost(model: string, pt: number, ct: number): number {
  const [pin, pout] = PRICES[model] ?? [0, 0];
  return Math.round(((pt * pin + ct * pout) / 1_000_000) * 1e7) / 1e7;
}

/** Deterministic PRNG so the fixture looks the same on every load. */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------------------------------------------------------- probe inputs

export const INPUTS: ProbeInput[] = [
  { id: "in1", args: { total: 100.0, n: 3 }, source: "model", note: "Total does not divide evenly into cents" },
  { id: "in2", args: { total: 50.0, n: 0 }, source: "model", note: "Nobody to split between" },
  { id: "in3", args: { total: 10.0, n: 4 }, source: "model", note: "Divides evenly" },
  { id: "in4", args: { total: 0.01, n: 2 }, source: "model", note: "Less than one cent per person" },
  { id: "in5", args: { total: 7.0, n: 3 }, source: "fuzz" },
  { id: "in6", args: { total: 19.99, n: 1 }, source: "fuzz" },
  { id: "in7", args: { total: 1234.56, n: 7 }, source: "fuzz" },
  { id: "in8", args: { total: 100.0, n: -2 }, source: "fuzz", note: "Negative head-count" },
  { id: "in9", args: { total: -30.0, n: 3 }, source: "model", note: "Negative total (a refund)" },
];

const ok = (v: string): Outcome => ({ ok: true, value_repr: v });
const err = (type: string, msg: string): Outcome => ({ ok: false, value_repr: type, error_type: type, error_msg: msg });

const SEVEN_FIRST = "[176.37, 176.37, 176.37, 176.37, 176.36, 176.36, 176.36]";
const SEVEN_DOWN = "[176.36, 176.36, 176.36, 176.36, 176.36, 176.36, 176.36]";
const SEVEN_UP = "[176.37, 176.37, 176.37, 176.37, 176.37, 176.37, 176.37]";

type BehaviourKey = "A" | "B" | "C" | "D" | "E";

const BEHAVIOUR: Record<BehaviourKey, Record<string, Outcome>> = {
  A: {
    in1: ok("[33.34, 33.33, 33.33]"),
    in2: err("ValueError", "n must be positive"),
    in3: ok("[2.5, 2.5, 2.5, 2.5]"),
    in4: ok("[0.01, 0.0]"),
    in5: ok("[2.34, 2.33, 2.33]"),
    in6: ok("[19.99]"),
    in7: ok(SEVEN_FIRST),
    in8: err("ValueError", "n must be positive"),
    in9: ok("[-10.0, -10.0, -10.0]"),
  },
  B: {
    in1: ok("[33.33, 33.33, 33.33]"),
    in2: err("ValueError", "n must be at least 1"),
    in3: ok("[2.5, 2.5, 2.5, 2.5]"),
    in4: ok("[0.0, 0.0]"),
    in5: ok("[2.33, 2.33, 2.33]"),
    in6: ok("[19.99]"),
    in7: ok(SEVEN_DOWN),
    in8: err("ValueError", "n must be at least 1"),
    in9: ok("[-10.0, -10.0, -10.0]"),
  },
  C: {
    in1: ok("[33.34, 33.34, 33.34]"),
    in2: err("ValueError", "n must be positive"),
    in3: ok("[2.5, 2.5, 2.5, 2.5]"),
    in4: ok("[0.01, 0.01]"),
    in5: ok("[2.34, 2.34, 2.34]"),
    in6: ok("[19.99]"),
    in7: ok(SEVEN_UP),
    in8: err("ValueError", "n must be positive"),
    in9: ok("[-10.0, -10.0, -10.0]"),
  },
  D: {
    in1: ok("[33.34, 33.33, 33.33]"),
    in2: ok("[]"),
    in3: ok("[2.5, 2.5, 2.5, 2.5]"),
    in4: ok("[0.01, 0.0]"),
    in5: ok("[2.34, 2.33, 2.33]"),
    in6: ok("[19.99]"),
    in7: ok(SEVEN_FIRST),
    in8: ok("[]"),
    in9: ok("[-10.0, -10.0, -10.0]"),
  },
  E: Object.fromEntries(
    INPUTS.map((i) => [i.id, err("TypeError", "'float' object cannot be interpreted as an integer")]),
  ),
};

// ---------------------------------------------------------------- code variants

const CODE: Record<BehaviourKey | "R", string[]> = {
  A: [
    `def split_bill(total: float, n: int) -> list[float]:
    """Split total evenly among n people, rounding to cents."""
    if n <= 0:
        raise ValueError("n must be positive")
    cents = round(total * 100)
    base, extra = divmod(cents, n)
    # the first \`extra\` people absorb one leftover cent each
    return [(base + (1 if i < extra else 0)) / 100 for i in range(n)]
`,
    `from decimal import Decimal, ROUND_DOWN


def split_bill(total: float, n: int) -> list[float]:
    if n < 1:
        raise ValueError("n must be positive")
    amount = Decimal(str(total))
    share = (amount / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    shares = [share] * n
    remainder = amount - share * n
    i = 0
    while remainder > 0:
        shares[i] += Decimal("0.01")
        remainder -= Decimal("0.01")
        i += 1
    return [float(s) for s in shares]
`,
    `def split_bill(total, n):
    """Return a list with each person's share of the bill."""
    if not isinstance(n, int) or n <= 0:
        raise ValueError("n must be positive")
    total_cents = int(round(total * 100))
    per_person = total_cents // n
    leftover = total_cents - per_person * n
    result = []
    for person in range(n):
        cents = per_person + (1 if person < leftover else 0)
        result.append(round(cents / 100, 2))
    return result
`,
  ],
  B: [
    `import math


def split_bill(total: float, n: int) -> list[float]:
    if n <= 0:
        raise ValueError("n must be at least 1")
    share = math.floor(total * 100 / n) / 100
    return [share] * n
`,
    `def split_bill(total: float, n: int) -> list[float]:
    """Everyone pays the same amount, truncated to whole cents."""
    if n <= 0:
        raise ValueError("n must be at least 1")
    each = int(round(total * 100)) // n
    return [each / 100 for _ in range(n)]
`,
  ],
  C: [
    `import math


def split_bill(total: float, n: int) -> list[float]:
    """Each person pays the same amount, rounded up so the bill is always covered."""
    if n <= 0:
        raise ValueError("n must be positive")
    share = math.ceil(round(total * 100) / n) / 100
    return [share for _ in range(n)]
`,
    `from decimal import Decimal, ROUND_UP


def split_bill(total: float, n: int) -> list[float]:
    if n <= 0:
        raise ValueError("n must be positive")
    share = (Decimal(str(total)) / n).quantize(Decimal("0.01"), rounding=ROUND_UP)
    return [float(share)] * n
`,
  ],
  D: [
    `def split_bill(total: float, n: int) -> list[float]:
    if n <= 0:
        return []
    cents = round(total * 100)
    base, extra = divmod(cents, n)
    return [(base + 1) / 100 if i < extra else base / 100 for i in range(n)]
`,
    `def split_bill(total: float, n: int) -> list[float]:
    """Split a bill; an empty party pays nothing."""
    shares: list[float] = []
    if n < 1:
        return shares
    cents = int(round(total * 100))
    for i in range(n):
        shares.append((cents // n + (1 if i < cents % n else 0)) / 100)
    return shares
`,
  ],
  E: [
    `def split_bill(total: float, n: int) -> list[float]:
    if n == 0:
        raise ValueError("n must be non-zero")
    cents = total * 100
    shares = [0] * n
    for c in range(cents):  # hand out the bill one cent at a time
        shares[c % n] += 1
    return [s / 100 for s in shares]
`,
  ],
  R: [
    `import os


def split_bill(total: float, n: int) -> list[float]:
    precision = int(os.environ.get("BILL_PRECISION", "2"))
    share = round(total / n, precision)
    return [share] * n
`,
  ],
};

// ---------------------------------------------------------------- allocation

/** How many implementations land in each behaviour for a given sample count (24 → 9/6/4/3/1 + 1 rejected). */
export function allocate(n: number): Record<BehaviourKey | "R", number> {
  const base: [BehaviourKey | "R", number][] = [
    ["A", 9],
    ["B", 6],
    ["C", 4],
    ["D", 3],
    ["E", 1],
    ["R", 1],
  ];
  const out = {} as Record<BehaviourKey | "R", number>;
  let used = 0;
  for (const [k, w] of base) {
    let c = Math.floor((w * n) / 24);
    if (["A", "B", "C", "D"].includes(k)) c = Math.max(1, c);
    out[k] = c;
    used += c;
  }
  out.A += n - used;
  return out;
}

// ---------------------------------------------------------------- reasoning excerpts

const FRAME_REASONING = `The user wants a function that divides a bill among N people with cent rounding. Signature: split_bill(total: float, n: int) -> list[float]. The spec is silent on three things I can see: what happens to the leftover cent when total*100 is not divisible by n (100.00 / 3), what happens when n is 0 or negative, and whether the shares must sum exactly to the total. Probe inputs should target each: 100.0/3 for the remainder, 50.0/0 and 100.0/-2 for degenerate head-counts, 0.01/2 for sub-cent shares, plus an even split as a control...`;

const EXPLAIN_REASONING = `Five clusters. A and D agree everywhere except n<=0: A raises ValueError, D returns []. So that's one question about degenerate input. A, B, C differ on 100.0/3: A hands the extra cent to the first person (sums to 100.00), B truncates everyone to 33.33 (one cent disappears), C rounds everyone up to 33.34 (collects 100.02). That is the core ambiguity: "evenly" vs "rounding to cents" conflict. Cluster E raises TypeError on every input including the even split 10.0/4 — range() over a float. Nobody would intend that; classify as likely_bug, not a meaning...`;

const CLARIFY_REASONING = `The user chose the leftover-cent rule and the degenerate-input rule. Rewrite the spec so a fresh implementer cannot diverge: state that amounts are handled in whole cents, the remainder goes one cent at a time to the first people in order, shares must sum exactly to the total, and n <= 0 raises ValueError. Include one worked example (100.00 between 3) because examples pin behaviour better than prose...`;

// ---------------------------------------------------------------- builders

export function makeTraceCall(
  r: () => number,
  purpose: string,
  model: string,
  thinking: boolean,
  startedAt: number,
  sizes: { pt: [number, number]; ct: [number, number]; lat: [number, number] },
  reasoning?: string,
): CallRecord {
  const pt = Math.round(sizes.pt[0] + r() * (sizes.pt[1] - sizes.pt[0]));
  const ct = Math.round(sizes.ct[0] + r() * (sizes.ct[1] - sizes.ct[0]));
  const lat = Math.round((sizes.lat[0] + r() * (sizes.lat[1] - sizes.lat[0])) * 1000) / 1000;
  return {
    purpose,
    model,
    thinking,
    latency_s: lat,
    prompt_tokens: pt,
    completion_tokens: ct,
    cost_usd: cost(model, pt, ct),
    ok: true,
    request_id: `chatcmpl-${Math.floor(r() * 0xffffffff).toString(16).padStart(8, "0")}${Math.floor(r() * 0xffff)
      .toString(16)
      .padStart(4, "0")}`,
    started_at: startedAt,
    reasoning_excerpt: reasoning,
  };
}

export function recomputeMetrics(run: Run, now: number): void {
  const m = run.metrics;
  m.n_calls = run.trace.length;
  m.prompt_tokens = run.trace.reduce((a, c) => a + c.prompt_tokens, 0);
  m.completion_tokens = run.trace.reduce((a, c) => a + c.completion_tokens, 0);
  m.total_cost_usd = Math.round(run.trace.reduce((a, c) => a + c.cost_usd, 0) * 1e7) / 1e7;
  m.wall_time_s = Math.round((now - run.created_at) * 10) / 10;
}

export type BuildOpts = {
  id: string;
  n?: number;
  spec?: string;
  isSample?: boolean;
  createdAt?: number;
  /** Fan-out models, assigned round-robin like the backend. Default: [FAST_MODEL]. */
  implementers?: string[];
  /** Mirror the backend's exception_types=true: failing outcomes become "raises:<Type>". */
  exceptionTypes?: boolean;
};

/** "ValueError" (fixture shorthand) -> "raises:ValueError" when exception types are on. */
export function typedRaises(repr: string, on: boolean | undefined): string {
  if (!on) return repr;
  return /^[A-Z]\w*(Error|Exception)$|^Timeout$/.test(repr) ? `raises:${repr}` : repr;
}

/** Complete run in `awaiting_answers` state. */
export function buildBillRun(opts: BuildOpts): Run {
  const n = opts.n ?? 24;
  const created = opts.createdAt ?? Date.now() / 1000;
  const implementers = opts.implementers?.length ? opts.implementers : [FAST_MODEL];
  const exTypes = !!opts.exceptionTypes;
  const typedOutcomes = (o: Record<string, Outcome>): Record<string, Outcome> =>
    exTypes
      ? Object.fromEntries(
          Object.entries(o).map(([k, v]) => [k, v.ok ? v : { ...v, value_repr: `raises:${v.error_type ?? "Exception"}` }]),
        )
      : o;
  const r = rng(1337 + n);
  const alloc = allocate(n);

  // Assign behaviours to indexes in a shuffled (but deterministic) order so clusters interleave in the grid.
  const keys: (BehaviourKey | "R")[] = [];
  (Object.keys(alloc) as (BehaviourKey | "R")[]).forEach((k) => {
    for (let i = 0; i < alloc[k]; i++) keys.push(k);
  });
  for (let i = keys.length - 1; i > 0; i--) {
    const j = Math.floor(r() * (i + 1));
    [keys[i], keys[j]] = [keys[j], keys[i]];
  }

  const variantCounter: Record<string, number> = {};
  const impls: Implementation[] = keys.map((k, idx) => {
    const v = variantCounter[k] ?? 0;
    variantCounter[k] = v + 1;
    const code = CODE[k][v % CODE[k].length];
    const id = `impl-${String(idx + 1).padStart(2, "0")}`;
    if (k === "R") {
      return {
        id,
        index: idx,
        model: implementers[idx % implementers.length],
        status: "rejected",
        code,
        reject_reason: "Static safety check: imports module 'os', which is not allowed in the sandbox.",
      };
    }
    return {
      id,
      index: idx,
      model: implementers[idx % implementers.length],
      status: "executed",
      code,
      cluster_id: `c${k}`,
      outcomes: typedOutcomes(BEHAVIOUR[k]),
    };
  });

  const executed = impls.filter((i) => i.status === "executed").length;
  const SUMMARIES: Record<BehaviourKey, string> = {
    A: "Works in whole cents; leftover cents go one each to the first people, so shares always sum to the total. Raises ValueError when n ≤ 0.",
    B: "Everyone pays the same amount rounded down to the cent; leftover cents silently disappear (100.00 / 3 collects 99.99).",
    C: "Everyone pays the same amount rounded up to the cent; the group over-pays (100.00 / 3 collects 100.02).",
    D: "Same cent distribution as A, but an empty or negative party returns [] instead of raising.",
    E: "Raises TypeError on every input — iterates range() over a float number of cents.",
  };
  const clusters: Cluster[] = (["A", "B", "C", "D", "E"] as BehaviourKey[])
    .map((k) => {
      const ids = impls.filter((i) => i.cluster_id === `c${k}`).map((i) => i.id);
      return {
        id: `c${k}`,
        label: k,
        impl_ids: ids,
        size: ids.length,
        share: executed ? ids.length / executed : 0,
        representative_impl_id: ids[0],
        kind: (k === "E" ? "crash" : "behavior") as Cluster["kind"],
        summary: SUMMARIES[k],
      };
    })
    .filter((c) => c.size > 0);
  const has = (id: string) => clusters.some((c) => c.id === id);
  const optionImplCount = (ids: string[]) => clusters.filter((c) => ids.includes(c.id)).reduce((a, c) => a + c.size, 0);
  const keep = (ids: string[]) => ids.filter(has);

  const questions: Question[] = [
    {
      id: "q1",
      kind: "ambiguity",
      text: "When the bill doesn't divide evenly into cents, who pays the leftover cent?",
      why: "100.00 split 3 ways is 33.333…. “Evenly” and “rounding to cents” can't both hold, and implementations resolve it three different ways: one changes who pays, one loses money, one over-charges the table.",
      witness_input_ids: ["in1", "in4"],
      options: [
        {
          id: "q1_first",
          label: "The first people in the list pay one extra cent each, so the shares add up exactly",
          cluster_ids: keep(["cA", "cD"]),
          examples: [
            { input_id: "in1", value_repr: "[33.34, 33.33, 33.33]" },
            { input_id: "in4", value_repr: "[0.01, 0.0]" },
          ],
        },
        {
          id: "q1_down",
          label: "Everyone pays the same amount, rounded down. The leftover cent is dropped",
          cluster_ids: keep(["cB"]),
          examples: [
            { input_id: "in1", value_repr: "[33.33, 33.33, 33.33]" },
            { input_id: "in4", value_repr: "[0.0, 0.0]" },
          ],
        },
        {
          id: "q1_up",
          label: "Everyone pays the same amount, rounded up. The table over-pays slightly",
          cluster_ids: keep(["cC"]),
          examples: [
            { input_id: "in1", value_repr: "[33.34, 33.34, 33.34]" },
            { input_id: "in4", value_repr: "[0.01, 0.01]" },
          ],
        },
      ],
    },
    {
      id: "q2",
      kind: "ambiguity",
      text: "What should happen when there is nobody to split the bill between (N = 0)?",
      why: "The spec never says N must be positive. Most implementations reject it, a few quietly return an empty list. Callers will rely on whichever you choose.",
      witness_input_ids: ["in2", "in8"],
      options: [
        {
          id: "q2_raise",
          label: "Reject it: raise ValueError",
          cluster_ids: keep(["cA", "cB", "cC"]),
          examples: [
            { input_id: "in2", value_repr: "ValueError" },
            { input_id: "in8", value_repr: "ValueError" },
          ],
        },
        {
          id: "q2_empty",
          label: "Return an empty list: nobody pays anything",
          cluster_ids: keep(["cD"]),
          examples: [
            { input_id: "in2", value_repr: "[]" },
            { input_id: "in8", value_repr: "[]" },
          ],
        },
      ],
    },
  ];
  if (has("cE")) {
    questions.push({
      id: "q3",
      kind: "likely_bug",
      text: "One implementation crashes even on a bill that splits evenly",
      why: "split_bill(total=10.0, n=4) raises TypeError: it loops over range(total * 100), which is a float. Every other implementation returns [2.5, 2.5, 2.5, 2.5]. Nobody means this, so it is a bug and not a reading of the spec.",
      witness_input_ids: ["in3"],
      options: [
        {
          id: "q3_ok",
          label: "Every other implementation",
          cluster_ids: keep(["cA", "cB", "cC", "cD"]),
          examples: [{ input_id: "in3", value_repr: "[2.5, 2.5, 2.5, 2.5]" }],
        },
        { id: "q3_crash", label: "Crashing implementation", cluster_ids: ["cE"], examples: [{ input_id: "in3", value_repr: "TypeError" }] },
      ],
    });
  }

  const consensus = keep(["cA", "cB", "cC", "cD"]);
  questions.push({
    id: "a0",
    kind: "assumption",
    text: "Can the total be negative, for example a refund?",
    why: "Every implementation accepted split_bill(-30.0, 3) and split the refund like a bill. Your spec never says whether a negative total is valid input or a caller error.",
    witness_input_ids: ["in9"],
    affected_input_ids: ["in9"],
    agree_count: optionImplCount(consensus),
    options: [
      {
        id: "a0keep",
        label: "Yes. Split refunds exactly like bills",
        cluster_ids: consensus,
        impl_count: optionImplCount(consensus),
        examples: [{ input_id: "in9", value_repr: "[-10.0, -10.0, -10.0]" }],
      },
      {
        id: "a0alt",
        label: "No. A negative total is invalid: raise ValueError",
        cluster_ids: [],
        impl_count: 0,
        examples: [],
        is_alternative: true,
        note: "split_bill(-30.0, 3) -> raises ValueError",
      },
    ],
  });
  // Server sends impl_count on every option.
  for (const q of questions)
    for (const o of q.options) {
      if (o.impl_count === undefined) o.impl_count = optionImplCount(o.cluster_ids);
      o.examples = o.examples.map((e) => ({ ...e, value_repr: typedRaises(e.value_repr, exTypes) }));
    }

  // Trace: frame (fast, thinking) → N implement calls (fast) → explain (deep, thinking).
  const trace: CallRecord[] = [];
  let t = created + 0.2;
  trace.push(
    makeTraceCall(r, "frame: signature + probe inputs", FAST_MODEL, true, t, { pt: [820, 900], ct: [1650, 1900], lat: [5.6, 6.6] }, FRAME_REASONING),
  );
  t += trace[0].latency_s + 0.1;
  impls.forEach((impl, i) => {
    trace.push(
      makeTraceCall(r, `implement #${String(impl.index + 1).padStart(2, "0")}`, impl.model, false, t + i * 0.035 + r() * 0.05, {
        pt: [410, 470],
        ct: [140, 360],
        lat: [1.1, 3.4],
      }),
    );
  });
  const fanEnd = Math.max(...trace.slice(1).map((c) => c.started_at + c.latency_s));
  trace.push(
    makeTraceCall(r, "explain: clusters → questions", DEEP_MODEL, true, fanEnd + 1.6, { pt: [2900, 3300], ct: [1300, 1600], lat: [7.2, 8.4] }, EXPLAIN_REASONING),
  );
  const end = trace[trace.length - 1].started_at + trace[trace.length - 1].latency_s + 0.2;

  const log: Run["log"] = [
    { t: created, stage: "frame", msg: `Run created · ${n} samples requested` },
    { t: created + 0.2, stage: "frame", msg: `${FAST_LABEL} is framing the spec (thinking on)…` },
    { t: trace[0].started_at + trace[0].latency_s, stage: "frame", msg: "Signature: split_bill(total: float, n: int) -> list[float] · 9 probe inputs (5 model, 4 fuzz)" },
    { t: trace[0].started_at + trace[0].latency_s + 0.1, stage: "fanout", msg: `Fanning out ${n} independent implementations on ${FAST_LABEL}` },
    { t: fanEnd, stage: "fanout", msg: `${n - alloc.R} generated · ${alloc.R} rejected by static safety check` },
    { t: fanEnd + 0.1, stage: "execute", msg: `Executing ${executed} implementations × ${INPUTS.length} inputs in the sandbox` },
    { t: fanEnd + 1.2, stage: "cluster", msg: `${clusters.length} behaviour clusters (${clusters.filter((c) => c.kind === "crash").length} crash)` },
    { t: fanEnd + 1.6, stage: "explain", msg: `${DEEP_LABEL} is turning disagreements into questions…` },
    { t: end, stage: "explain", msg: `${questions.filter((q) => q.kind === "ambiguity").length} ambiguities · ${questions.filter((q) => q.kind === "assumption").length} silent assumption · ${questions.filter((q) => q.kind === "likely_bug").length} likely bug` },
  ];

  const run: Run = {
    id: opts.id,
    created_at: created,
    updated_at: end,
    status: "awaiting_answers",
    stage: "done",
    spec: opts.spec ?? BILL_SPEC,
    preset_id: "bill-split",
    is_sample: !!opts.isSample,
    settings: { n_samples: n, fast_model: FAST_MODEL, deep_model: DEEP_MODEL, implementers, exception_types: exTypes },
    signature: {
      name: "split_bill",
      params: [
        { name: "total", type: "float", description: "Bill total in currency units, e.g. 100.0" },
        { name: "n", type: "int", description: "Number of people sharing the bill" },
      ],
      returns: { type: "list[float]", description: "Each person's share, in person order" },
      docstring: "Split a restaurant bill evenly among n people, rounding to cents.",
    },
    inputs: INPUTS,
    implementations: impls,
    clusters,
    questions,
    trace,
    metrics: { total_cost_usd: 0, prompt_tokens: 0, completion_tokens: 0, n_calls: 0, wall_time_s: 0 },
    log,
  };
  recomputeMetrics(run, end);
  return run;
}

// ---------------------------------------------------------------- resolution

const Q1_SPEC: Record<string, string> = {
  q1_first:
    "Work in whole cents. When the total does not divide evenly, give the leftover cents one at a time to the first people in the list, so the shares always add up exactly to the total (100.00 split 3 ways is [33.34, 33.33, 33.33]).",
  q1_down:
    "Every person pays the same amount, rounded down to the cent. Leftover cents are dropped, so the shares may add up to slightly less than the total (100.00 split 3 ways is [33.33, 33.33, 33.33]).",
  q1_up:
    "Every person pays the same amount, rounded up to the cent, so the shares always cover the total and may exceed it slightly (100.00 split 3 ways is [33.34, 33.34, 33.34]).",
};
const Q2_SPEC: Record<string, string> = {
  q2_raise: "If N is zero or negative, raise ValueError.",
  q2_empty: "If N is zero or negative, return an empty list.",
};
const Q1_DECISION: Record<string, string> = {
  q1_first: "Leftover cents go one each to the first people, in order. The shares always add up exactly to the total.",
  q1_down: "Every share is rounded down to the cent. Leftover cents are dropped.",
  q1_up: "Every share is rounded up to the cent. The table may over-pay by up to N−1 cents.",
};
const Q2_DECISION: Record<string, string> = {
  q2_raise: "N ≤ 0 is invalid input and raises ValueError.",
  q2_empty: "N ≤ 0 returns [] (nobody pays).",
};

/** Python literal for fixture args: ints stay ints, "total" is always a float. */
function pyArg(key: string, v: unknown): string {
  if (typeof v === "number") return key === "total" && Number.isInteger(v) ? `${v}.0` : String(v);
  return JSON.stringify(v);
}

function kwargs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => `"${k}": ${pyArg(k, v)}`)
    .join(", ");
}

function wrap(text: string, width: number): string[] {
  const out: string[] = [];
  let line = "";
  for (const w of text.split(/\s+/)) {
    if (line && (line + " " + w).length > width) {
      out.push(line);
      line = w;
    } else line = line ? `${line} ${w}` : w;
  }
  if (line) out.push(line);
  return out;
}

export function buildTests(run: Run, cases: Resolution["locked_cases"], spec: string): string {
  const fn = run.signature?.name ?? "fn";
  const isRaise = (r: string) => /^(raises:)?[A-Z]\w*(Error|Exception)$/.test(r);
  const values = cases.filter((c) => !isRaise(c.expected_repr));
  const raises = cases
    .filter((c) => isRaise(c.expected_repr))
    .map((c) => ({ ...c, expected_repr: c.expected_repr.replace(/^raises:/, "") }));
  const lines = [
    `"""Locked-behaviour tests generated by SpecFork.`,
    ``,
    ...wrap(`Spec: ${spec}`, 88),
    `Every case below is a witness input on which independent implementations disagreed`,
    `(or a control they agreed on). Expected values come from the behaviour you chose.`,
    `"""`,
    `import pytest`,
    ``,
    `from solution import ${fn}`,
    ``,
    `VALUE_CASES = [`,
    ...values.map((c) => `    ({${kwargs(c.args)}}, ${c.expected_repr}),  # ${c.input_id}`),
    `]`,
    ``,
  ];
  if (raises.length) {
    lines.push(`RAISING_CASES = [`, ...raises.map((c) => `    ({${kwargs(c.args)}}, ${c.expected_repr}),  # ${c.input_id}`), `]`, ``);
  }
  lines.push(
    ``,
    `@pytest.mark.parametrize("kwargs, expected", VALUE_CASES)`,
    `def test_${fn}_locked_values(kwargs, expected):`,
    `    assert ${fn}(**kwargs) == expected`,
    ``,
  );
  if (raises.length) {
    lines.push(
      ``,
      `@pytest.mark.parametrize("kwargs, exc", RAISING_CASES)`,
      `def test_${fn}_rejects_invalid_input(kwargs, exc):`,
      `    with pytest.raises(exc):`,
      `        ${fn}(**kwargs)`,
      ``,
    );
  }
  return lines.join("\n");
}

export const CUSTOM_IMPL_ID = "impl-custom";

/**
 * Resolution for whatever answers the user picked (mock mirrors the backend's intent). `other` holds free-text
 * answers: the mock treats them like the most common behaviour for values, writes the user's words into the spec,
 * "writes" a custom reference implementation (returned as customImpl) and leaves one split case open.
 */
export function buildResolution(
  run: Run,
  answers: Record<string, string>,
  other: Record<string, string> = {},
): { resolution: Resolution; trace: CallRecord; customImpl?: Implementation } {
  const custom = (qid: string) => (other[qid] ?? "").trim();
  const q1 = custom("q1") ? "q1_first" : (answers.q1 ?? "q1_first");
  const q2 = custom("q2") ? "q2_raise" : (answers.q2 ?? "q2_raise");
  const a0 = custom("a0") ? "a0keep" : (answers.a0 ?? "a0keep");
  const overrides = a0 === "a0alt" ? ["in9"] : [];
  const open = custom("q1") ? ["in7"] : [];
  const opt = (qid: string, oid: string) => run.questions.find((q) => q.id === qid)?.options.find((o) => o.id === oid);
  const set1 = new Set(opt("q1", q1)?.cluster_ids ?? []);
  const surviving = (opt("q2", q2)?.cluster_ids ?? []).filter((c) => set1.has(c));
  const behaviourKey = (surviving[0] ?? [...set1][0] ?? "cA").slice(1) as BehaviourKey;
  const chosenCluster = run.clusters.find((c) => c.id === `c${behaviourKey}`);
  const chosenImpl = run.implementations.find((i) => i.id === chosenCluster?.representative_impl_id);

  // Expected behaviour: q1 decides values, q2 decides degenerate inputs.
  const valueKey: BehaviourKey = q1 === "q1_down" ? "B" : q1 === "q1_up" ? "C" : "A";
  const expectedRaw = (inputId: string): string => {
    if (inputId === "in2" || inputId === "in8") return q2 === "q2_empty" ? "[]" : "ValueError";
    if (inputId === "in9") return "[-10.0, -10.0, -10.0]";
    return BEHAVIOUR[valueKey][inputId].value_repr;
  };
  const expected = (inputId: string) => typedRaises(expectedRaw(inputId), run.settings.exception_types);
  const locked = run.inputs
    .filter((i) => !overrides.includes(i.id) && !open.includes(i.id))
    .map((i) => ({ input_id: i.id, args: i.args, expected_repr: expected(i.id) }));
  const forked = run.implementations.filter((i) => i.id !== CUSTOM_IMPL_ID);
  const matches = forked.filter(
    (impl) => impl.outcomes && locked.every((c) => impl.outcomes![c.input_id]?.value_repr === c.expected_repr),
  ).length;

  const a0Spec = custom("a0")
    ? `For a negative total: ${custom("a0")}.`
    : a0 === "a0alt"
      ? "A negative total is invalid: raise ValueError."
      : "A negative total (a refund) is split the same way.";
  const a0Decision = custom("a0")
    ? `Negative totals: ${custom("a0")} (your own answer).`
    : a0 === "a0alt"
      ? "Negative totals raise ValueError. This overrides what every implementation assumed."
      : "Negative totals (refunds) are split like any other bill.";
  const q1Spec = custom("q1") ? `Leftover cents: ${custom("q1")}.` : Q1_SPEC[q1];
  const q2Spec = custom("q2") ? `If N is zero or negative: ${custom("q2")}.` : Q2_SPEC[q2];
  const q1Decision = custom("q1") ? `Leftover cents: ${custom("q1")} (your own answer).` : Q1_DECISION[q1];
  const q2Decision = custom("q2") ? `N ≤ 0: ${custom("q2")} (your own answer).` : Q2_DECISION[q2];
  const clarified = `${BILL_SPEC} ${q1Spec} ${q2Spec} ${a0Spec} Return a list of N floats, one per person, in order.`;
  const decisions = [q1Decision, q2Decision, a0Decision, "The result has N floats in person order, each with at most 2 decimal places."];
  const baseRef =
    q1 === "q1_first" && q2 === "q2_raise"
      ? CODE.A[0]
      : q1 === "q1_first"
        ? CODE.D[0]
        : (q1 === "q1_down" ? CODE.B[1] : CODE.C[0]).replace(
            /raise ValueError\(("n must be (?:positive|at least 1)")\)/,
            q2 === "q2_empty" ? "return []" : "raise ValueError($1)",
          );
  const refCode =
    a0 === "a0alt"
      ? baseRef.replace(/(def split_bill[^\n]*\n(?: {4}"""[^\n]*\n)?)/, '$1    if total < 0:\n        raise ValueError("total must not be negative")\n')
      : baseRef;

  const anyCustom = Object.values(other).some((t) => t.trim());
  const customImpl: Implementation | undefined = anyCustom
    ? {
        id: CUSTOM_IMPL_ID,
        index: forked.length,
        model: run.settings.deep_model,
        status: "executed",
        code: refCode,
        outcomes: Object.fromEntries(
          run.inputs.map((i) => [i.id, expected(i.id) === "ValueError" ? { ok: false, value_repr: "ValueError", error_type: "ValueError", error_msg: "n must be positive" } : { ok: true, value_repr: expected(i.id) }]),
        ),
      }
    : undefined;

  const r = rng(99);
  const now = Date.now() / 1000;
  return {
    resolution: {
      answers: { ...answers },
      surviving_cluster_ids: surviving,
      chosen_impl_id: chosenImpl?.id ?? run.implementations[0].id,
      clarified_spec: clarified,
      decisions,
      tests_code: buildTests(run, locked, clarified),
      reference_code: refCode,
      locked_cases: locked,
      agreement_before: forked.length ? matches / forked.length : 0,
      agreement_before_counts: [matches, forked.length],
      unlocked_input_ids: overrides,
      open_input_ids: open,
      ...(customImpl ? { custom_impl_id: customImpl.id } : {}),
    },
    trace: makeTraceCall(r, "clarify: rewrite spec from answers", run.settings.deep_model, true, now, { pt: [1400, 1600], ct: [700, 900], lat: [3.8, 4.6] }, CLARIFY_REASONING),
    customImpl,
  };
}

/** Final convergence numbers for a re-fork of n implementations. */
export function convergenceResult(n: number): { passed: number; clusters_after: number } {
  const passed = Math.max(1, Math.round(n * 0.917));
  return { passed, clusters_after: passed === n ? 1 : 2 };
}

export const MIXED_SAMPLE_RUN_ID = "sample-bill-split-mixed";

/** Recorded mixed-model run (Lightning + Super fan-out) with exception types on. */
export function mixedSampleRun(): Run {
  const run = buildBillRun({
    id: MIXED_SAMPLE_RUN_ID,
    n: 24,
    isSample: true,
    createdAt: Date.UTC(2026, 9, 29, 9, 2, 41) / 1000,
    implementers: [FAST_MODEL, SUPER_MODEL],
    exceptionTypes: true,
  });
  run.log[3] = { ...run.log[3], msg: "Fanning out 24 independent implementations on Nemotron 3.5 Lightning + Nemotron 3 Super" };
  return run;
}

export function sampleRun(): Run {
  // Recorded "yesterday" so the banner date looks plausible.
  return buildBillRun({ id: SAMPLE_RUN_ID, n: 24, isSample: true, createdAt: Date.UTC(2026, 9, 28, 21, 14, 7) / 1000 });
}
