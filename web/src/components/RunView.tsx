import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, type Api } from "../api";
import {
  activeClusterIds,
  ambiguityQuestions,
  answersFromRun,
  clusterStyles,
} from "../lib/clusters";
import { formatDate } from "../lib/format";
import { useRun } from "../lib/useRun";
import type { Implementation, Run, RunStatus } from "../types";
import { IconAlert, IconArrowRight, IconInfo, IconTerminal } from "./Icons";
import { ClusterLegend, GridStatusLegend, ImplGrid, type Focus } from "./ImplGrid";
import { ImplDrawer } from "./ImplDrawer";
import { ClusterBar, LikelyBugs, LockBar, MeaningsHeader, QuestionCard } from "./Meanings";
import { LiveLog, Stepper } from "./Pipeline";
import { ResolutionView } from "./Resolution";
import { TraceDrawer, TraceSummary } from "./Trace";

const STATUS_PILL: Record<RunStatus, { label: string; cls: string; live?: boolean }> = {
  running: { label: "Running live", cls: "border-accent/40 bg-accent/10 text-accent-strong", live: true },
  awaiting_answers: { label: "Waiting for your answers", cls: "border-warn/40 bg-warn/10 text-warn" },
  resolving: { label: "Writing clarified spec", cls: "border-accent/40 bg-accent/10 text-accent-strong", live: true },
  resolved: { label: "Resolved", cls: "border-add/40 bg-add/10 text-add" },
  converging: { label: "Re-forking", cls: "border-accent/40 bg-accent/10 text-accent-strong", live: true },
  error: { label: "Error", cls: "border-danger/40 bg-danger/10 text-danger" },
};

function StatusPill({ status }: { status: RunStatus }) {
  const s = STATUS_PILL[status] ?? STATUS_PILL.running;
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[13.5px] font-semibold ${s.cls}`}>
      <span className={`h-2 w-2 rounded-full bg-current ${s.live ? "pulse-dot" : ""}`} aria-hidden />
      {s.label}
    </span>
  );
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429) return `Rate limited: ${e.detail}`;
    return e.detail;
  }
  return e instanceof Error ? e.message : String(e);
}

function SampleBanner({ run, onForkLive }: { run: Run; onForkLive: () => void }) {
  return (
    <div className="mb-5 flex flex-col gap-3 rounded-2xl border border-accent/25 bg-accent/[0.07] px-5 py-3.5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3 text-[15px] text-fog-200">
        <IconInfo className="shrink-0 text-accent" size={20} />
        <span>
          <span className="font-semibold text-fog-50">Recorded run from {formatDate(run.created_at)}.</span> Click{" "}
          <em>Fork it</em> to run it live.
        </span>
      </div>
      <button type="button" className="btn btn-ghost shrink-0 border-accent/30 py-2" onClick={onForkLive}>
        Fork it live <IconArrowRight size={16} />
      </button>
    </div>
  );
}

function RunSkeleton() {
  return (
    <div className="mx-auto max-w-[1600px] px-4 py-8 sm:px-6 lg:px-10" aria-busy="true" aria-label="Loading run">
      <div className="shimmer h-24 rounded-2xl border border-white/[0.06] bg-white/[0.02]" />
      <div className="mt-6 grid gap-6 lg:grid-cols-[340px_1fr]">
        <div className="shimmer h-[420px] rounded-2xl border border-white/[0.06] bg-white/[0.02]" />
        <div className="shimmer h-[420px] rounded-2xl border border-white/[0.06] bg-white/[0.02]" />
      </div>
    </div>
  );
}

export function RunView({
  api,
  id,
  onHome,
  onForkSpec,
}: {
  api: Api;
  id: string;
  onHome: () => void;
  onForkSpec: (spec: string) => void;
}) {
  const { run, error, follow } = useRun(api, id);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [hover, setHover] = useState<string | null>(null);
  const [openImpl, setOpenImpl] = useState<Implementation | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const [lockBusy, setLockBusy] = useState(false);
  const [lockErr, setLockErr] = useState<string | null>(null);
  const [convBusy, setConvBusy] = useState(false);
  const [convErr, setConvErr] = useState<string | null>(null);
  const meaningsRef = useRef<HTMLDivElement>(null);
  const resolutionRef = useRef<HTMLDivElement>(null);
  const prevStatus = useRef<RunStatus | null>(null);
  const seededFor = useRef<string | null>(null);

  // Seed answers from the server once per run (e.g. a resolved sample run).
  useEffect(() => {
    if (run && seededFor.current !== run.id) {
      seededFor.current = run.id;
      setAnswers(answersFromRun(run));
    }
  }, [run]);

  // Scroll to the next thing to look at when the run advances live (not on first load).
  useEffect(() => {
    if (!run) return;
    const prev = prevStatus.current;
    prevStatus.current = run.status;
    if (!prev || prev === run.status) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const go = (el: HTMLElement | null) =>
      window.setTimeout(() => el?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" }), 350);
    if (prev === "running" && run.status === "awaiting_answers") go(meaningsRef.current);
    if (prev === "resolving" && run.status === "resolved") go(resolutionRef.current);
  }, [run]);

  const styles = useMemo(() => clusterStyles(run?.clusters ?? []), [run?.clusters]);
  const locked = !!run && (!!run.resolution || ["resolving", "resolved", "converging"].includes(run.status));
  const active = useMemo(() => {
    if (!run) return null;
    if (run.resolution && run.resolution.surviving_cluster_ids.length) return new Set(run.resolution.surviving_cluster_ids);
    return activeClusterIds(run.questions, answers);
  }, [run, answers]);
  const focus: Focus = { active, hover };

  const lock = useCallback(async () => {
    if (!run) return;
    setLockBusy(true);
    setLockErr(null);
    try {
      const amb = Object.fromEntries(ambiguityQuestions(run.questions).map((q) => [q.id, answers[q.id]]));
      const next = await api.postAnswers(run.id, amb);
      follow(next);
    } catch (e) {
      setLockErr(errMsg(e));
    } finally {
      setLockBusy(false);
    }
  }, [api, run, answers, follow]);

  const converge = useCallback(async () => {
    if (!run) return;
    setConvBusy(true);
    setConvErr(null);
    try {
      const next = await api.converge(run.id, run.settings.n_samples);
      follow(next);
    } catch (e) {
      setConvErr(errMsg(e));
    } finally {
      setConvBusy(false);
    }
  }, [api, run, follow]);

  if (error && !run) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <div className="mx-auto max-w-[720px] px-4 py-24 text-center">
        <IconAlert size={36} className="mx-auto text-warn" />
        <h1 className="mt-4 font-display text-[28px] font-semibold text-fog-50">
          {notFound ? "Run not found" : "Couldn't load this run"}
        </h1>
        <p className="mt-2 text-[16px] text-fog-400">
          {notFound ? "It may have expired, or the link is incomplete." : errMsg(error)}
        </p>
        <button type="button" className="btn btn-primary mt-6" onClick={onHome}>
          Write a new spec
        </button>
      </div>
    );
  }
  if (!run) return <RunSkeleton />;

  const amb = ambiguityQuestions(run.questions);
  const answeredCount = amb.filter((q) => answers[q.id]).length;
  const showMeanings = run.clusters.length > 0 && run.questions.length > 0;
  const executed = run.implementations.filter((i) => i.status === "executed").length;
  const rejected = run.implementations.filter((i) => i.status === "rejected").length;
  const written = run.implementations.filter((i) => i.status !== "pending").length;

  return (
    <div className="mx-auto max-w-[1600px] px-4 pb-24 pt-6 sm:px-6 lg:px-10">
      {run.is_sample && <SampleBanner run={run} onForkLive={() => onForkSpec(run.spec)} />}

      <section className="card mb-6 flex flex-col gap-4 p-5 sm:flex-row sm:items-start sm:justify-between sm:p-6" aria-label="Spec">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <span className="eyebrow">Spec</span>
            <StatusPill status={run.status} />
          </div>
          <p className="mono mt-2.5 text-[18px] leading-relaxed text-fog-50 sm:text-[20px]">{run.spec}</p>
          {run.signature && (
            <p className="mono mt-2 text-[14px] text-fog-400">
              <span className="text-[#b9a6ff]">def</span> <span className="text-[#7cc8f2]">{run.signature.name}</span>(
              {run.signature.params.map((p, i) => (
                <span key={p.name}>
                  {i > 0 && ", "}
                  <span className="text-fog-200">{p.name}</span>: {p.type}
                </span>
              ))}
              ) → {run.signature.returns.type}
            </p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <button type="button" className="btn btn-ghost lg:hidden" onClick={() => setTraceOpen(true)}>
            <IconTerminal size={16} /> Trace
          </button>
          <button type="button" className="btn btn-ghost" onClick={onHome}>
            New spec
          </button>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)] xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="space-y-4 lg:sticky lg:top-[88px] lg:self-start" aria-label="Pipeline">
          <div className="card p-4 sm:p-5">
            <h2 className="eyebrow mb-4">Pipeline</h2>
            <Stepper run={run} />
            <div className="mt-5">
              <LiveLog run={run} />
            </div>
          </div>
          <div className="hidden lg:block">
            <TraceSummary run={run} onOpen={() => setTraceOpen(true)} />
          </div>
        </aside>

        <main className="min-w-0 space-y-6">
          <section className="card p-5 sm:p-6" aria-labelledby="impl-h">
            <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 id="impl-h" className="font-display text-[22px] font-semibold text-fog-50">
                  {run.settings.n_samples} independent implementations
                </h2>
                <p className="mt-0.5 text-[14.5px] tabular-nums text-fog-400">
                  {written} written · {executed} executed{rejected ? ` · ${rejected} rejected` : ""}
                  {run.clusters.length ? ` · ${run.clusters.length} behaviour clusters` : ""}. Click any tile to read its code.
                </p>
              </div>
              {run.clusters.length > 0 ? (
                <ClusterLegend clusters={run.clusters} styles={styles} onHover={setHover} focus={focus} />
              ) : (
                <GridStatusLegend />
              )}
            </div>
            <ImplGrid
              impls={run.implementations}
              styles={styles}
              focus={focus}
              onOpen={setOpenImpl}
              expected={run.settings.n_samples}
            />
          </section>

          {run.status === "error" && (
            <div role="alert" className="flex gap-3 rounded-2xl border border-danger/30 bg-danger/[0.07] p-5">
              <IconAlert className="mt-0.5 shrink-0 text-danger" size={22} />
              <div>
                <div className="font-display text-[18px] font-semibold text-fog-50">The run stopped with an error</div>
                <p className="mono mt-1 text-[14px] text-fog-300">{run.error ?? "Unknown error."}</p>
                <div className="mt-3 flex gap-2">
                  <button type="button" className="btn btn-primary" onClick={() => onForkSpec(run.spec)}>
                    Try again
                  </button>
                  <button type="button" className="btn btn-ghost" onClick={() => setTraceOpen(true)}>
                    Inspect trace
                  </button>
                </div>
              </div>
            </div>
          )}

          {run.status !== "error" && run.stage === "done" && run.clusters.length > 0 && run.questions.length === 0 && (
            <div className="card p-6">
              <h2 className="font-display text-[26px] font-semibold text-fog-50">No ambiguity found</h2>
              <p className="mt-2 text-fog-300">Every implementation behaved identically on every probe input. Your spec is already pinned down.</p>
            </div>
          )}

          <AnimatePresence>
            {showMeanings && (
              <motion.div
                ref={meaningsRef}
                className="scroll-mt-24 space-y-5"
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.45 }}
              >
                <section className="card p-5 sm:p-7" aria-label="Meanings">
                  <MeaningsHeader run={run} />
                  <div className="mt-6">
                    <ClusterBar clusters={run.clusters} styles={styles} focus={focus} onHover={setHover} />
                  </div>
                </section>
                {amb.map((q, i) => (
                  <QuestionCard
                    key={q.id}
                    run={run}
                    q={q}
                    idx={i}
                    answer={answers[q.id]}
                    readOnly={locked}
                    styles={styles}
                    onAnswer={(opt) => setAnswers((a) => ({ ...a, [q.id]: opt }))}
                    onHover={setHover}
                  />
                ))}
                <LikelyBugs run={run} styles={styles} />
                {amb.length > 0 && (
                  <LockBar
                    answered={answeredCount}
                    total={amb.length}
                    busy={lockBusy || run.status === "resolving"}
                    locked={locked && run.status !== "resolving"}
                    error={lockErr}
                    onLock={lock}
                  />
                )}
              </motion.div>
            )}
          </AnimatePresence>

          {run.status === "resolving" && !run.resolution && (
            <div className="card flex items-center gap-4 p-6" aria-live="polite">
              <span className="h-6 w-6 animate-spin rounded-full border-2 border-accent/30 border-t-accent" aria-hidden />
              <div>
                <div className="font-display text-[18px] font-semibold text-fog-50">Writing your clarified spec…</div>
                <div className="text-[14.5px] text-fog-400">
                  Nemotron 3 Ultra is folding your answers into the spec. Tests are generated deterministically from the witnesses.
                </div>
              </div>
            </div>
          )}

          {run.resolution && (
            <motion.div
              ref={resolutionRef}
              className="scroll-mt-24"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45 }}
            >
              <ResolutionView api={api} run={run} busy={convBusy} error={convErr} onConverge={converge} />
            </motion.div>
          )}

          <div className="lg:hidden">
            <TraceSummary run={run} onOpen={() => setTraceOpen(true)} />
          </div>
        </main>
      </div>

      <ImplDrawer
        run={run}
        impl={openImpl ? (run.implementations.find((i) => i.id === openImpl.id) ?? openImpl) : null}
        styles={styles}
        onClose={() => setOpenImpl(null)}
      />
      <TraceDrawer run={run} open={traceOpen} onClose={() => setTraceOpen(false)} />
    </div>
  );
}
