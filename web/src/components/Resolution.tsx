import { AnimatePresence, motion } from "framer-motion";
import { useMemo, useState } from "react";
import type { Api } from "../api";
import { wordDiff } from "../lib/diff";
import { formatPct } from "../lib/format";
import type { Convergence, Run } from "../types";
import { CodeBlock, CopyButton } from "./CodeBlock";
import { CountUpPct } from "./CountUp";
import { IconArrowRight, IconCheck, IconCode, IconDownload, IconRefresh, IconX } from "./Icons";

export function SpecDiff({ before, after }: { before: string; after: string }) {
  const segs = useMemo(() => wordDiff(before, after), [before, after]);
  return (
    <p className="whitespace-pre-line text-[18px] leading-[1.75] text-fog-200 sm:text-[19px]">
      {segs.map((s, i) =>
        s.type === "same" ? (
          <span key={i}>{s.text}</span>
        ) : s.type === "add" ? (
          <span key={i}>
            {s.text.match(/^\s*/)![0]}
          <ins
            className="rounded-[4px] bg-add/[0.13] px-0.5 text-fog-50 underline decoration-add/70 decoration-2 underline-offset-[5px] [box-decoration-break:clone]"
          >
            {s.text.trim()}
          </ins>
            {/\S\s+$/.test(s.text) ? s.text.match(/\s+$/)![0] : ""}
          </span>
        ) : (
          <del key={i} className="text-fog-500 decoration-danger/60">
            {s.text}
          </del>
        ),
      )}
    </p>
  );
}

function CodeTabs({ api, run }: { api: Api; run: Run }) {
  const r = run.resolution!;
  const [tab, setTab] = useState<"tests" | "ref">("tests");
  const tabs = [
    { id: "tests" as const, label: "tests.py", sub: `${r.locked_cases.length} locked cases · pytest`, code: r.tests_code },
    { id: "ref" as const, label: "reference.py", sub: "Implementation matching your answers", code: r.reference_code },
  ];
  const cur = tabs.find((t) => t.id === tab)!;
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] px-4 pt-3 sm:px-5">
        <div role="tablist" aria-label="Generated files" className="flex gap-1">
          {tabs.map((t) => (
            <button
              key={t.id}
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={tab === t.id}
              aria-controls={`panel-${t.id}`}
              tabIndex={tab === t.id ? 0 : -1}
              onClick={() => setTab(t.id)}
              onKeyDown={(e) => {
                if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                  const next = tab === "tests" ? "ref" : "tests";
                  setTab(next);
                  document.getElementById(`tab-${next}`)?.focus();
                }
              }}
              className={`mono -mb-px rounded-t-lg border-b-2 px-4 py-2.5 text-[14.5px] font-medium transition-colors ${
                tab === t.id ? "border-fog-100 text-fog-50" : "border-transparent text-fog-400 hover:text-fog-100"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 pb-2.5">
          <CopyButton text={cur.code} />
          {tab === "tests" && (
            <a className="btn btn-ghost px-3 py-1.5 text-[13px]" href={api.testsUrl(run)} download="tests.py">
              <IconDownload size={15} /> tests.py
            </a>
          )}
          <a className="btn btn-ghost px-3 py-1.5 text-[13px]" href={api.exportUrl(run)} download={`specfork-${run.id}.md`}>
            <IconDownload size={15} /> export.md
          </a>
        </div>
      </div>
      <div id={`panel-${cur.id}`} role="tabpanel" aria-labelledby={`tab-${cur.id}`} className="p-4 sm:p-5">
        <p className="mb-3 text-[13.5px] text-fog-400">{cur.sub}</p>
        <CodeBlock code={cur.code} maxHeight={460} label={cur.label} />
      </div>
    </div>
  );
}

type TileState = "pending" | "generated" | "pass" | "fail" | "rejected";

/** Per-tile state: prefer the backend's per-impl list, else derive from passed/n. */
export function convergenceTileStates(conv: Convergence): TileState[] {
  const done = conv.status === "done";
  if (conv.implementations?.length) {
    return conv.implementations.map((i) => {
      if (i.status === "rejected" || i.status === "error") return done ? "fail" : "rejected";
      if (i.status === "executed") {
        if (i.passes_locked === true) return "pass";
        if (i.passes_locked === false) return "fail";
        return "generated";
      }
      if (i.status === "generated") return "generated";
      return done ? "fail" : "pending";
    });
  }
  return Array.from({ length: conv.n }, (_, i) => (i < conv.passed ? "pass" : done ? "fail" : "pending"));
}

function ConvergenceTiles({ conv }: { conv: Convergence }) {
  const states = convergenceTileStates(conv);
  return (
    <div className="grid grid-cols-8 gap-1.5 sm:grid-cols-12" aria-hidden>
      {states.map((st, i) => (
        <motion.div
          key={i}
          className={`flex aspect-square items-center justify-center rounded-md border ${
            st === "pass"
              ? "border-add/40 bg-add text-ink-950"
              : st === "fail"
                ? "border-danger/40 bg-danger/20 text-danger"
                : st === "generated"
                  ? "border-white/25 bg-white/[0.07] text-fog-300"
                  : st === "rejected"
                    ? "border-white/10 bg-[#2a3047] text-fog-400"
                    : "shimmer border-dashed border-white/15 bg-white/[0.02]"
          }`}
          initial={false}
          animate={{ scale: st === "pass" || st === "fail" ? [0.85, 1] : 1 }}
          transition={{ duration: 0.25 }}
        >
          {st === "pass" && <IconCheck size={13} strokeWidth={3} />}
          {st === "fail" && <IconX size={13} strokeWidth={2.6} />}
          {st === "generated" && <IconCode size={12} />}
        </motion.div>
      ))}
    </div>
  );
}

function MetricBar({ label, value, tone }: { label: string; value: number; tone: "before" | "after" }) {
  return (
    <div>
      <div className="mb-1.5 flex justify-between text-[13.5px] text-fog-400">
        <span>{label}</span>
        <span className="tabular-nums text-fog-200">{formatPct(value)}</span>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-white/[0.07]">
        <motion.div
          className={`h-full rounded-full ${tone === "after" ? "bg-add" : "bg-fog-400"}`}
          initial={{ width: 0 }}
          animate={{ width: `${value * 100}%` }}
          transition={{ duration: 1.1, ease: [0.2, 0.8, 0.2, 1] }}
        />
      </div>
    </div>
  );
}

export function AgreementPanel({
  run,
  busy,
  error,
  onConverge,
  convergeLabel,
}: {
  run: Run;
  busy: boolean;
  error: string | null;
  onConverge: () => void;
  convergeLabel?: string;
}) {
  const r = run.resolution!;
  const conv = r.convergence;
  const nOrig = r.agreement_before_counts?.[1] ?? run.implementations.length;
  const matched = r.agreement_before_counts?.[0] ?? Math.round(r.agreement_before * nOrig);
  const convDenom = conv ? (conv.executed ?? conv.n) : 0;
  const converging = run.status === "converging" || conv?.status === "running";
  const done = conv?.status === "done";
  const nClustersBefore = run.clusters.length;

  return (
    <section className="card relative overflow-hidden p-5 sm:p-7" aria-labelledby="agree-h">
      <div
        className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-add/10 blur-3xl"
        aria-hidden
        style={{ opacity: done ? 1 : 0.3 }}
      />
      <p className="eyebrow" id="agree-h">
        Agreement with your intent
      </p>

      <AnimatePresence mode="wait">
        {!done ? (
          <motion.div key="before" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="mt-2 flex flex-wrap items-end gap-x-5 gap-y-2">
              <CountUpPct value={r.agreement_before} className="font-display text-[72px] font-bold leading-none tracking-[-0.04em] text-fog-50 tabular-nums sm:text-[88px]" />
              <p className="max-w-[440px] pb-2 text-[16px] leading-snug text-fog-300">
                of implementations matched what you meant: <span className="font-semibold text-fog-50">{matched} of {nOrig}</span>{" "}
                original implementations pass every locked case.
              </p>
            </div>
            <p className="mt-4 max-w-[720px] text-[15px] leading-relaxed text-fog-400">
              With the original spec, a coding agent had roughly a {formatPct(r.agreement_before)} chance of guessing your
              intent. Re-fork the <em>clarified</em> spec into fresh, independent implementations to measure how much
              the ambiguity has shrunk.
            </p>
          </motion.div>
        ) : (
          <motion.div key="after" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            <div className="mt-3 flex items-center gap-x-4 gap-y-3 sm:gap-x-6">
              <span className="font-display text-[48px] font-bold leading-none tracking-[-0.04em] text-fog-400 tabular-nums sm:text-[80px]">
                {formatPct(r.agreement_before)}
              </span>
              <IconArrowRight size={44} className="h-8 w-8 text-fog-500 sm:h-11 sm:w-11" />
              <CountUpPct
                value={conv!.agreement_after}
                duration={1.4}
                className="font-display text-[60px] font-bold leading-none tracking-[-0.04em] text-add tabular-nums sm:text-[104px]"
              />
            </div>
            <p className="mt-3 max-w-[760px] text-[16px] leading-relaxed text-fog-300">
              <span className="font-semibold text-fog-50">
                {conv!.passed} of {convDenom}
              </span>{" "}
              fresh implementations of the clarified spec pass every locked case. Distinct behaviours went from{" "}
              <span className="font-semibold text-fog-50">{nClustersBefore}</span> to{" "}
              <span className="font-semibold text-fog-50">{conv!.clusters_after}</span>.
            </p>
            <div className="mt-5 grid max-w-[720px] gap-3">
              <MetricBar label="Original spec" value={r.agreement_before} tone="before" />
              <MetricBar label="Clarified spec" value={conv!.agreement_after} tone="after" />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {(converging || done) && conv && (
        <div className="mt-6">
          <div className="mb-2 flex items-center justify-between text-[13.5px] text-fog-400">
            <span>{converging ? "Re-forking the clarified spec…" : "Re-forked implementations"}</span>
            <span className="tabular-nums">
              {converging
                ? `${convergenceTileStates(conv).filter((x) => x !== "pending").length} of ${conv.n} written`
                : `${conv.passed} passing · ${convDenom - conv.passed} differ${conv.n > convDenom ? ` · ${conv.n - convDenom} didn't run` : ""}`}
            </span>
          </div>
          <ConvergenceTiles conv={conv} />
        </div>
      )}
      {conv?.status === "error" && (
        <p role="alert" className="mt-4 text-[14.5px] text-danger">
          The re-fork failed. {run.error ?? "Try again."}
        </p>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={`btn ${done ? "btn-ghost" : "btn-primary"} px-5 py-3 text-[16px]`}
          onClick={onConverge}
          disabled={busy || converging}
        >
          {busy || converging ? (
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-current/30 border-t-current" aria-hidden />
          ) : (
            <IconRefresh size={18} />
          )}
          {converging ? "Re-forking…" : convergeLabel ?? (done ? "Re-fork again" : "Re-fork clarified spec")}
        </button>
        {!done && !converging && (
          <span className="text-[14px] text-fog-500">{run.settings.n_samples} fresh implementations · same models · same probes</span>
        )}
        {error && (
          <span role="alert" className="text-[14px] text-danger">
            {error}
          </span>
        )}
      </div>
    </section>
  );
}

export function ResolutionView({
  api,
  run,
  busy,
  error,
  onConverge,
  convergeLabel,
}: {
  api: Api;
  run: Run;
  busy: boolean;
  error: string | null;
  onConverge: () => void;
  convergeLabel?: string;
}) {
  const r = run.resolution!;
  return (
    <div className="space-y-6">
      <div className="grid gap-6 2xl:grid-cols-[1.15fr_1fr]">
        <section className="card p-5 sm:p-7" aria-labelledby="clar-h">
          <p className="eyebrow" id="clar-h">
            Clarified spec
          </p>
          <div className="mt-3">
            <SpecDiff before={run.spec} after={r.clarified_spec} />
          </div>
          <div className="mt-3 flex items-center gap-3 text-[13px] text-fog-500">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-4 rounded-sm bg-add/25 ring-1 ring-add/60" /> added by your answers
            </span>
            <CopyButton text={r.clarified_spec} label="Copy spec" />
          </div>
          <h3 className="eyebrow mt-7">Decisions</h3>
          <ul className="mt-3 space-y-2.5">
            {r.decisions.map((d, i) => (
              <li key={i} className="flex gap-3 text-[16px] leading-snug text-fog-200">
                <span className="mt-[3px] flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-add/15 text-add">
                  <IconCheck size={13} strokeWidth={2.8} />
                </span>
                {d}
              </li>
            ))}
          </ul>
        </section>
        <AgreementPanel run={run} busy={busy} error={error} onConverge={onConverge} convergeLabel={convergeLabel} />
      </div>
      <CodeTabs api={api} run={run} />
    </div>
  );
}
