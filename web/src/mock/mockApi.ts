// In-browser fake backend. Replays the bill-splitting fixture as a live run so the whole flow can be clicked through.
import type { Health, Implementation, Preset, Run, RunSummary } from "../types";
import {
  BILL_SPEC,
  DEEP_MODEL,
  FAST_MODEL,
  SAMPLE_RUN_ID,
  buildBillRun,
  buildResolution,
  convergenceResult,
  makeTraceCall,
  recomputeMetrics,
  rng,
  sampleRun,
} from "./billFixture";

export const MOCK_PRESETS: Preset[] = [
  {
    id: "bill-split",
    title: "Split the bill",
    spec: BILL_SPEC,
    tagline: "Who pays the leftover cent?",
    sample_run_id: SAMPLE_RUN_ID,
  },
  {
    id: "dedupe-emails",
    title: "Deduplicate emails",
    spec: "Remove duplicate email addresses from a list, keeping the original order.",
    tagline: "Is Bob@X.com the same as bob@x.com?",
  },
  {
    id: "business-days",
    title: "Business days",
    spec: "Return the number of business days between two dates.",
    tagline: "Inclusive? Exclusive? Holidays?",
  },
  {
    id: "slugify",
    title: "Slugify a title",
    spec: "Turn an article title into a URL slug.",
    tagline: "Unicode, punctuation, max length…",
  },
];

type Listener = (run: Run) => void;

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const now = () => Date.now() / 1000;
const ACTIVE = new Set(["running", "resolving", "converging"]);

class MockServer {
  runs = new Map<string, Run>();
  listeners = new Map<string, Set<{ onRun: Listener; onEnd: () => void }>>();
  timers: number[] = [];
  counter = 0;

  constructor() {
    this.runs.set(SAMPLE_RUN_ID, sampleRun());
  }

  emit(id: string) {
    const run = this.runs.get(id);
    if (!run) return;
    run.updated_at = now();
    const snap = clone(run);
    this.listeners.get(id)?.forEach((l) => {
      l.onRun(snap);
      if (!ACTIVE.has(run.status)) l.onEnd();
    });
  }

  at(ms: number, fn: () => void) {
    this.timers.push(window.setTimeout(fn, ms));
  }

  get(id: string): Run {
    let run = this.runs.get(id);
    if (!run) {
      // Unknown id after a reload: regenerate a finished run so shared mock links still work.
      run = buildBillRun({ id, n: 24 });
      this.runs.set(id, run);
    }
    return run;
  }

  create(spec: string, n: number): string {
    const id = `mock-${Date.now().toString(36)}-${(this.counter++).toString(36)}`;
    const final = buildBillRun({ id, n, spec: spec.trim() || BILL_SPEC, createdAt: now() });
    const t0 = now();
    const run: Run = {
      ...clone(final),
      created_at: t0,
      updated_at: t0,
      status: "running",
      stage: "frame",
      signature: undefined,
      inputs: [],
      implementations: [],
      clusters: [],
      questions: [],
      trace: [],
      log: [{ t: t0, stage: "frame", msg: `Run created · ${n} samples requested` }],
      metrics: { total_cost_usd: 0, prompt_tokens: 0, completion_tokens: 0, n_calls: 0, wall_time_s: 0 },
    };
    this.runs.set(id, run);
    const log = (stage: Run["log"][number]["stage"], msg: string) => run.log.push({ t: now(), stage, msg });
    const tick = () => {
      recomputeMetrics(run, now());
      this.emit(id);
    };
    const pushTrace = (i: number) => {
      run.trace.push({ ...final.trace[i], started_at: now() - final.trace[i].latency_s });
    };

    this.at(350, () => {
      log("frame", "Nemotron 3 Ultra is framing the spec (thinking on)…");
      tick();
    });
    this.at(2300, () => {
      run.signature = final.signature;
      run.inputs = final.inputs;
      pushTrace(0);
      log("frame", final.log[2].msg);
      run.stage = "fanout";
      log("fanout", `Fanning out ${n} independent implementations on Nemotron 3.5 Lightning`);
      run.implementations = final.implementations.map(
        (impl): Implementation => ({ id: impl.id, index: impl.index, model: impl.model, status: "pending" }),
      );
      tick();
    });

    // Generation: tiles flip pending → generated (or rejected) in a shuffled order.
    const r = rng(7 + n);
    const order = final.implementations.map((_, i) => i).sort(() => r() - 0.5);
    const genStart = 2700;
    const genSpan = 3600;
    order.forEach((idx, k) => {
      this.at(genStart + (genSpan * k) / order.length + r() * 90, () => {
        const f = final.implementations[idx];
        const impl = run.implementations[idx];
        impl.code = f.code;
        if (f.status === "rejected") {
          impl.status = "rejected";
          impl.reject_reason = f.reject_reason;
        } else impl.status = "generated";
        pushTrace(1 + idx);
        tick();
      });
    });

    const execStart = genStart + genSpan + 400;
    const executable = final.implementations.filter((i) => i.status !== "rejected");
    this.at(execStart, () => {
      run.stage = "execute";
      log("fanout", final.log[4].msg);
      log("execute", final.log[5].msg);
      tick();
    });
    executable.forEach((f, k) => {
      this.at(execStart + 200 + (2000 * k) / executable.length, () => {
        const impl = run.implementations[f.index];
        impl.status = "executed";
        impl.outcomes = f.outcomes;
        tick();
      });
    });

    const clusterAt = execStart + 2600;
    this.at(clusterAt, () => {
      run.stage = "cluster";
      log("cluster", "Fingerprinting outputs and grouping identical behaviour…");
      tick();
    });
    this.at(clusterAt + 900, () => {
      run.clusters = final.clusters;
      run.implementations.forEach((impl, i) => (impl.cluster_id = final.implementations[i].cluster_id));
      log("cluster", final.log[6].msg);
      run.stage = "explain";
      log("explain", final.log[7].msg);
      tick();
    });
    this.at(clusterAt + 3600, () => {
      run.questions = final.questions;
      pushTrace(final.trace.length - 1);
      log("explain", final.log[8].msg);
      run.stage = "done";
      run.status = "awaiting_answers";
      tick();
    });
    return id;
  }

  answers(id: string, answers: Record<string, string>): Run {
    const run = this.get(id);
    run.questions.forEach((q) => {
      if (answers[q.id]) q.answer_option_id = answers[q.id];
    });
    run.status = "resolving";
    run.log.push({ t: now(), stage: "resolve", msg: "Nemotron 3 Ultra is rewriting the spec from your answers…" });
    this.at(150, () => this.emit(id));
    this.at(2600, () => {
      const { resolution, trace } = buildResolution(run, answers);
      run.resolution = resolution;
      run.trace.push(trace);
      run.log.push({ t: now(), stage: "resolve", msg: `Clarified spec + ${resolution.locked_cases.length} locked test cases ready` });
      run.status = "resolved";
      recomputeMetrics(run, now());
      this.emit(id);
    });
    return clone(run);
  }

  converge(id: string, n?: number): Run {
    const run = this.get(id);
    if (!run.resolution) throw new MockHttpError(409, "Answer the questions first.");
    const total = n ?? run.settings.n_samples;
    const { passed, clusters_after } = convergenceResult(total);
    run.status = "converging";
    run.resolution.convergence = { n: total, passed: 0, agreement_after: 0, clusters_after: 0, status: "running" };
    run.log.push({ t: now(), stage: "converge", msg: `Re-forking the clarified spec into ${total} fresh implementations…` });
    this.at(150, () => this.emit(id));
    const r = rng(4242);
    const span = 4600;
    for (let k = 0; k < total; k++) {
      this.at(600 + (span * k) / total, () => {
        const c = run.resolution!.convergence!;
        run.trace.push(
          makeTraceCall(r, `re-fork #${String(k + 1).padStart(2, "0")}`, FAST_MODEL, false, now(), {
            pt: [520, 600],
            ct: [140, 340],
            lat: [1.0, 3.1],
          }),
        );
        if (k < passed) c.passed = k + 1;
        recomputeMetrics(run, now());
        this.emit(id);
      });
    }
    this.at(600 + span + 700, () => {
      const c = run.resolution!.convergence!;
      c.passed = passed;
      c.agreement_after = passed / total;
      c.clusters_after = clusters_after;
      c.status = "done";
      run.status = "resolved";
      run.log.push({
        t: now(),
        stage: "converge",
        msg: `${passed}/${total} fresh implementations pass every locked case · ${clusters_after} behaviours remain`,
      });
      recomputeMetrics(run, now());
      this.emit(id);
    });
    return clone(run);
  }

  subscribe(id: string, onRun: Listener, onEnd: () => void): () => void {
    const entry = { onRun, onEnd };
    if (!this.listeners.has(id)) this.listeners.set(id, new Set());
    this.listeners.get(id)!.add(entry);
    const run = this.get(id);
    window.setTimeout(() => {
      onRun(clone(run));
      if (!ACTIVE.has(run.status)) onEnd();
    }, 0);
    return () => this.listeners.get(id)?.delete(entry);
  }

  list(): RunSummary[] {
    return [...this.runs.values()]
      .sort((a, b) => b.created_at - a.created_at)
      .map((r) => ({
        id: r.id,
        created_at: r.created_at,
        status: r.status,
        spec: r.spec,
        n_clusters: r.clusters.length,
        is_sample: r.is_sample,
      }));
  }
}

export class MockHttpError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

let server: MockServer | null = null;
export function mockServer(): MockServer {
  if (!server) server = new MockServer();
  return server;
}

export const MOCK_HEALTH: Health = {
  ok: true,
  llm_configured: true,
  models: { fast: FAST_MODEL, deep: DEEP_MODEL },
  version: "mock",
};
