import { AnimatePresence, motion } from "framer-motion";
import type { ClusterStyle } from "../lib/clusters";
import { ambiguityQuestions, likelyBugQuestions, optionImplCount } from "../lib/clusters";
import { formatCall, formatPct, isErrorRepr } from "../lib/format";
import type { Cluster, Question, QuestionOption, Run } from "../types";
import { IconBug, IconCheck, IconLock } from "./Icons";
import type { Focus } from "./ImplGrid";
import { ClusterSwatch } from "./ImplDrawer";

export function ClusterBar({
  clusters,
  styles,
  focus,
  onHover,
}: {
  clusters: Cluster[];
  styles: Record<string, ClusterStyle>;
  focus: Focus;
  onHover: (id: string | null) => void;
}) {
  const total = clusters.reduce((a, c) => a + c.share, 0) || 1;
  const isDim = (id: string) => (focus.hover ? focus.hover !== id : focus.active ? !focus.active.has(id) : false);
  return (
    <div>
      <div
        className="flex h-[52px] w-full gap-[3px] overflow-hidden rounded-xl"
        role="img"
        aria-label={`Behaviour clusters: ${clusters.map((c) => `${c.label} ${formatPct(c.share)}`).join(", ")}`}
      >
        {clusters.map((c, i) => {
          const s = styles[c.id];
          const pct = (c.share / total) * 100;
          return (
            <motion.div
              key={c.id}
              className={`relative flex min-w-[28px] items-center justify-start overflow-hidden px-3 transition-[opacity,filter] duration-300 ${
                s?.crash ? "stripes text-white" : "text-ink-950"
              } ${isDim(c.id) ? "opacity-20 saturate-[0.3]" : ""} ${i === 0 ? "rounded-l-xl" : ""} ${
                i === clusters.length - 1 ? "rounded-r-xl" : ""
              }`}
              style={{ background: s?.crash ? undefined : s?.color }}
              initial={{ width: 0 }}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.7, delay: i * 0.06, ease: [0.2, 0.8, 0.2, 1] }}
              onMouseEnter={() => onHover(c.id)}
              onMouseLeave={() => onHover(null)}
            >
              <span
                className={`font-display text-[18px] font-bold leading-none ${s?.crash ? "rounded bg-ink-950/70 px-1.5 py-0.5" : ""}`}
              >
                {c.label}
              </span>
              {pct > 9 && <span className="ml-2 text-[14px] font-semibold tabular-nums opacity-75">{formatPct(c.share)}</span>}
            </motion.div>
          );
        })}
      </div>
      <ul className="mt-4 grid gap-2.5 md:grid-cols-2">
        {clusters.map((c) => (
          <li
            key={c.id}
            className={`flex gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-3 transition-opacity duration-300 ${
              isDim(c.id) ? "opacity-35" : ""
            }`}
            onMouseEnter={() => onHover(c.id)}
            onMouseLeave={() => onHover(null)}
          >
            <span className="mt-0.5 flex flex-col items-center gap-1">
              <ClusterSwatch style={styles[c.id]} size={16} />
              <span className="font-display text-[15px] font-bold text-fog-50">{c.label}</span>
            </span>
            <div className="min-w-0">
              <div className="text-[13px] tabular-nums text-fog-400">
                {c.size} implementation{c.size === 1 ? "" : "s"} · {formatPct(c.share)}
                {c.kind === "crash" && <span className="ml-1.5 text-danger">· crashes</span>}
              </div>
              <p className="mt-0.5 text-[14.5px] leading-snug text-fog-200">{c.summary ?? "No summary yet."}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Witness({ run, inputId, value }: { run: Run; inputId: string; value: string }) {
  const inp = run.inputs.find((i) => i.id === inputId);
  const err = isErrorRepr(value);
  return (
    <div className="mono flex flex-wrap items-baseline gap-x-2 text-[13.5px] leading-relaxed">
      <span className="text-fog-300">{inp ? formatCall(run.signature?.name, inp.args) : inputId}</span>
      <span className="text-fog-500" aria-hidden>
        →
      </span>
      <span className="sr-only">returns</span>
      <span className={err ? "text-danger" : "font-medium text-fog-50"}>{err ? `raises ${value}` : value}</span>
    </div>
  );
}

function OptionCard({
  run,
  q,
  opt,
  selected,
  readOnly,
  styles,
  total,
  onSelect,
  onHover,
}: {
  run: Run;
  q: Question;
  opt: QuestionOption;
  selected: boolean;
  readOnly: boolean;
  styles: Record<string, ClusterStyle>;
  total: number;
  onSelect: () => void;
  onHover: (id: string | null) => void;
}) {
  const count = optionImplCount(run.clusters, opt.cluster_ids);
  const share = total ? count / total : 0;
  return (
    <label
      className={`group relative flex h-full cursor-pointer flex-col rounded-2xl border p-4 transition-[border-color,background-color,box-shadow,opacity] duration-200 ${
        selected
          ? "border-fog-100/80 bg-white/[0.07] shadow-[0_0_0_1px_rgba(231,236,245,0.5),0_12px_30px_-16px_rgba(165,180,252,0.5)]"
          : "border-white/10 bg-white/[0.02] hover:border-white/25 hover:bg-white/[0.04]"
      } ${readOnly && !selected ? "opacity-45" : ""} ${readOnly ? "cursor-default" : ""} has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent`}
      onMouseEnter={() => opt.cluster_ids.length === 1 && onHover(opt.cluster_ids[0])}
      onMouseLeave={() => onHover(null)}
    >
      <input
        type="radio"
        className="sr-only"
        name={`q-${q.id}`}
        value={opt.id}
        checked={selected}
        disabled={readOnly && !selected}
        onChange={() => !readOnly && onSelect()}
      />
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 flex h-[20px] w-[20px] shrink-0 items-center justify-center rounded-full border-2 transition-colors ${
            selected ? "border-fog-50 bg-fog-50 text-ink-900" : "border-fog-500"
          }`}
          aria-hidden
        >
          {selected && <IconCheck size={12} strokeWidth={3} />}
        </span>
        <span className="text-[16px] font-semibold leading-snug text-fog-50">{opt.label}</span>
      </div>
      <div className="mt-3 space-y-1 rounded-xl bg-ink-950/60 px-3 py-2.5">
        {opt.examples.map((ex) => (
          <Witness key={ex.input_id} run={run} inputId={ex.input_id} value={ex.value_repr} />
        ))}
      </div>
      <div className="mt-auto pt-3.5">
        <div className="flex items-center justify-between gap-2 text-[13.5px]">
          <span className="flex items-center gap-1.5">
            {opt.cluster_ids.map((cid) => (
              <span key={cid} className="inline-flex items-center gap-1 text-fog-300">
                <ClusterSwatch style={styles[cid]} size={11} />
                <span className="font-display font-semibold">{styles[cid]?.label ?? cid}</span>
              </span>
            ))}
          </span>
          <span className="tabular-nums text-fog-300">
            chosen by <span className="font-semibold text-fog-50">{count}</span> of {total} implementations
          </span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.06]" aria-hidden>
          <motion.div
            className="h-full rounded-full bg-fog-300/70"
            initial={{ width: 0 }}
            animate={{ width: `${share * 100}%` }}
            transition={{ duration: 0.6 }}
          />
        </div>
      </div>
    </label>
  );
}

export function QuestionCard({
  run,
  q,
  idx,
  answer,
  readOnly,
  styles,
  onAnswer,
  onHover,
}: {
  run: Run;
  q: Question;
  idx: number;
  answer?: string;
  readOnly: boolean;
  styles: Record<string, ClusterStyle>;
  onAnswer: (optId: string) => void;
  onHover: (id: string | null) => void;
}) {
  const total = run.implementations.length;
  const cols = q.options.length >= 3 ? "lg:grid-cols-3" : "md:grid-cols-2";
  return (
    <motion.section
      className="card p-5 sm:p-6"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 + idx * 0.08 }}
      aria-labelledby={`q-${q.id}-text`}
    >
      <div className="flex items-start gap-4">
        <span
          className={`flex h-9 min-w-9 items-center justify-center rounded-lg px-2 font-display text-[15px] font-bold ${
            answer ? "bg-fog-100 text-ink-900" : "bg-white/[0.07] text-fog-200"
          }`}
        >
          {answer ? <IconCheck size={17} strokeWidth={2.6} /> : `Q${idx + 1}`}
        </span>
        <div className="min-w-0">
          <h3 id={`q-${q.id}-text`} className="font-display text-[21px] font-semibold leading-snug text-fog-50 sm:text-[23px]">
            {q.text}
          </h3>
          <p className="mt-1.5 max-w-[900px] text-[15px] leading-relaxed text-fog-400">
            <span className="font-semibold text-fog-300">Why it matters: </span>
            {q.why}
          </p>
        </div>
      </div>
      <div role="radiogroup" aria-labelledby={`q-${q.id}-text`} className={`mt-5 grid gap-3 ${cols}`}>
        {q.options.map((opt) => (
          <OptionCard
            key={opt.id}
            run={run}
            q={q}
            opt={opt}
            selected={answer === opt.id}
            readOnly={readOnly}
            styles={styles}
            total={total}
            onSelect={() => onAnswer(opt.id)}
            onHover={onHover}
          />
        ))}
      </div>
    </motion.section>
  );
}

export function LikelyBugs({ run, styles }: { run: Run; styles: Record<string, ClusterStyle> }) {
  const bugs = likelyBugQuestions(run.questions);
  if (!bugs.length) return null;
  return (
    <section className="rounded-2xl border border-dashed border-white/12 bg-white/[0.015] p-5" aria-labelledby="bugs-h">
      <h3 id="bugs-h" className="flex items-center gap-2 font-display text-[17px] font-semibold text-fog-100">
        <IconBug className="text-danger" /> Probably bugs, not meanings
        <span className="ml-1 text-[13px] font-normal text-fog-500">Informational. No answer needed.</span>
      </h3>
      <ul className="mt-3 space-y-4">
        {bugs.map((b) => (
          <li key={b.id}>
            <div className="text-[16px] font-semibold text-fog-100">{b.text}</div>
            <p className="mt-1 text-[14.5px] leading-relaxed text-fog-400">{b.why}</p>
            <div className="mt-2.5 flex flex-wrap gap-2.5">
              {b.options.map((o) => (
                <div key={o.id} className="rounded-xl border border-white/[0.07] bg-ink-950/50 px-3 py-2">
                  <div className="mb-1 flex items-center gap-1.5 text-[12.5px] text-fog-400">
                    {o.cluster_ids.map((cid) => (
                      <ClusterSwatch key={cid} style={styles[cid]} size={10} />
                    ))}
                    {o.label} · {optionImplCount(run.clusters, o.cluster_ids)} impl.
                  </div>
                  {o.examples.map((ex) => (
                    <Witness key={ex.input_id} run={run} inputId={ex.input_id} value={ex.value_repr} />
                  ))}
                </div>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function MeaningsHeader({ run }: { run: Run }) {
  const k = run.clusters.filter((c) => c.kind === "behavior").length;
  const crash = run.clusters.filter((c) => c.kind === "crash").length;
  const q = ambiguityQuestions(run.questions).length;
  const executed = run.implementations.filter((i) => i.status === "executed").length;
  return (
    <div>
      <p className="eyebrow">Result</p>
      <h2 className="mt-1 font-display text-[32px] font-bold leading-tight tracking-[-0.02em] text-fog-50 sm:text-[40px]">
        Your spec has <span className="text-accent-strong">{k}</span> meaning{k === 1 ? "" : "s"}.
      </h2>
      <p className="mt-2 max-w-[860px] text-[16px] leading-relaxed text-fog-300">
        {executed} implementations ran on {run.inputs.length} probe inputs and split into {k} distinct behaviour
        {k === 1 ? "" : "s"}
        {crash ? ` (plus ${crash} that crash${crash === 1 ? "es" : ""})` : ""}.{" "}
        {q > 0 ? (
          <>
            {q === 1 ? "One question settles" : `${q} questions settle`} it. Pick the behaviour you meant.
          </>
        ) : (
          "No ambiguities found: every implementation agrees."
        )}
      </p>
    </div>
  );
}

export function LockBar({
  answered,
  total,
  busy,
  locked,
  error,
  onLock,
}: {
  answered: number;
  total: number;
  busy: boolean;
  locked: boolean;
  error: string | null;
  onLock: () => void;
}) {
  const ready = answered === total && total > 0;
  return (
    <div className="sticky bottom-4 z-20">
      <div className="card flex flex-col gap-3 border-white/12 bg-ink-800/95 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex gap-1" aria-hidden>
            {Array.from({ length: total }, (_, i) => (
              <span key={i} className={`h-2 w-7 rounded-full transition-colors ${i < answered ? "bg-fog-100" : "bg-white/12"}`} />
            ))}
          </div>
          <span className="text-[15px] text-fog-300" aria-live="polite">
            {locked ? (
              "Answers locked."
            ) : (
              <>
                <span className="font-semibold tabular-nums text-fog-50">
                  {answered} of {total}
                </span>{" "}
                answered{ready ? ": ready to lock in" : ""}
              </>
            )}
          </span>
          <AnimatePresence>
            {error && (
              <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} role="alert" className="text-[14px] text-danger">
                {error}
              </motion.span>
            )}
          </AnimatePresence>
        </div>
        {!locked && (
          <button type="button" className="btn btn-primary px-6 py-3 text-[16px]" disabled={!ready || busy} onClick={onLock}>
            {busy ? (
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-900/30 border-t-ink-900" aria-hidden />
            ) : (
              <IconLock size={17} />
            )}
            {busy ? "Locking…" : "Lock it in"}
          </button>
        )}
      </div>
    </div>
  );
}
