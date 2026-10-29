import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef } from "react";
import { STAGES, stageIndex } from "../lib/clusters";
import type { Run } from "../types";
import { IconCheck, IconX } from "./Icons";

function stageDetail(run: Run, id: string): string | null {
  const impls = run.implementations;
  switch (id) {
    case "frame":
      return run.signature ? `${run.inputs.length} probe inputs` : null;
    case "fanout": {
      if (!impls.length) return null;
      const done = impls.filter((i) => i.status !== "pending").length;
      return `${done}/${impls.length} written`;
    }
    case "execute": {
      const ex = impls.filter((i) => i.status === "executed" || i.status === "error").length;
      const runnable = impls.filter((i) => i.status !== "rejected").length;
      return ex ? `${ex}/${runnable} ran` : null;
    }
    case "cluster":
      return run.clusters.length ? `${run.clusters.length} clusters` : null;
    case "explain": {
      const q = run.questions.filter((x) => x.kind === "ambiguity").length;
      return run.questions.length ? `${q} question${q === 1 ? "" : "s"}` : null;
    }
  }
  return null;
}

export function Stepper({ run }: { run: Run }) {
  const cur = stageIndex(run.stage);
  const failed = run.status === "error";
  const running = run.status === "running";
  return (
    <ol className="grid grid-cols-5 gap-1.5 lg:grid-cols-1 lg:gap-0" aria-label="Pipeline progress">
      {STAGES.map((s, i) => {
        const done = i < cur || (!running && !failed);
        const active = i === cur && running;
        const errored = failed && i === cur;
        const detail = stageDetail(run, s.id);
        return (
          <li key={s.id} className="relative lg:flex lg:gap-3.5 lg:pb-4 last:lg:pb-0" aria-current={active ? "step" : undefined}>
            {i < STAGES.length - 1 && (
              <span
                className={`absolute left-[13px] top-[30px] hidden h-[calc(100%-26px)] w-px lg:block ${done ? "bg-fog-400/50" : "bg-white/10"}`}
                aria-hidden
              />
            )}
            <span
              className={`relative z-[1] mx-auto flex h-[28px] w-[28px] shrink-0 items-center justify-center rounded-full border text-[12.5px] font-semibold transition-colors lg:mx-0 ${
                errored
                  ? "border-danger bg-danger/15 text-danger"
                  : done
                    ? "border-fog-100 bg-fog-100 text-ink-900"
                    : active
                      ? "border-accent bg-accent/15 text-accent-strong"
                      : "border-white/15 text-fog-500"
              }`}
            >
              {errored ? <IconX size={14} /> : done ? <IconCheck size={15} strokeWidth={2.4} /> : i + 1}
              {active && <span className="absolute inset-[-4px] rounded-full border border-accent/40 pulse-dot" aria-hidden />}
            </span>
            <div className="mt-1.5 min-w-0 text-center lg:mt-0 lg:text-left">
              <div
                className={`font-display text-[13px] font-semibold sm:text-[15px] lg:text-[16px] ${
                  active ? "text-fog-50" : done ? "text-fog-100" : "text-fog-500"
                }`}
              >
                {s.label}
              </div>
              <div className="hidden text-[13.5px] leading-snug text-fog-400 lg:block">
                {s.blurb}
                {detail && (
                  <span className={`ml-1.5 tabular-nums ${active ? "text-accent-strong" : "text-fog-300"}`}>· {detail}</span>
                )}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function relTime(run: Run, t: number): string {
  const rel = t > 1e6 ? t - run.created_at : t;
  return `+${Math.max(0, rel).toFixed(1)}s`;
}

export function LiveLog({ run }: { run: Run }) {
  const ref = useRef<HTMLDivElement>(null);
  const lines = run.log.slice(-60);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);
  const active = run.status === "running" || run.status === "resolving" || run.status === "converging";
  return (
    <div
      ref={ref}
      className="mono scroll-thin max-h-[170px] overflow-y-auto lg:max-h-[230px] rounded-xl border border-white/[0.06] bg-ink-950/70 px-3.5 py-3 text-[12.5px] leading-[1.7]"
      role="log"
      aria-live="polite"
      aria-label="Live pipeline log"
      tabIndex={0}
    >
      <AnimatePresence initial={false}>
        {lines.map((l, i) => (
          <motion.div
            key={`${l.t}-${i}-${l.msg.slice(0, 12)}`}
            initial={{ opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex gap-2.5"
          >
            <span className="shrink-0 tabular-nums text-fog-500">{relTime(run, l.t)}</span>
            <span className="w-[62px] shrink-0 text-accent/80">{i > 0 && lines[i - 1].stage === l.stage ? "" : l.stage}</span>
            <span className="min-w-0 break-words text-fog-200">{l.msg}</span>
          </motion.div>
        ))}
      </AnimatePresence>
      {active && (
        <div className="flex items-center gap-2 text-fog-500">
          <span className="pulse-dot inline-block h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
          working…
        </div>
      )}
      {!lines.length && !active && <div className="text-fog-500">No log lines.</div>}
    </div>
  );
}
