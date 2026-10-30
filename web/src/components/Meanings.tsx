import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import type { ClusterStyle } from "../lib/clusters";
import {
  ambiguityQuestions,
  answerableQuestions,
  assumptionQuestions,
  likelyBugQuestions,
  optionCompatible,
  optionCount,
  OTHER_MAX,
  OTHER_MIN,
  otherValid,
} from "../lib/clusters";
import { formatCall, formatPct, isErrorRepr } from "../lib/format";
import type { Cluster, Question, QuestionOption, Run } from "../types";
import { IconAlert, IconBug, IconCheck, IconLock } from "./Icons";
import type { Focus } from "./ImplGrid";
import { ClusterSwatch } from "./ClusterSwatch";

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
              } ${isDim(c.id) ? "opacity-30 saturate-[0.4]" : ""} ${i === 0 ? "rounded-l-xl" : ""} ${
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
              {pct > 9 && <span className="ml-2 hidden text-[14px] sm:inline font-semibold tabular-nums opacity-75">{formatPct(c.share)}</span>}
            </motion.div>
          );
        })}
      </div>
      <ul className="mt-4 grid gap-2.5 md:grid-cols-2">
        {clusters.map((c) => (
          <li
            key={c.id}
            className={`flex gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-3 transition-opacity duration-300 ${
              isDim(c.id) ? "opacity-45" : ""
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
      <span className="text-fog-300">{inp ? formatCall(run.signature?.name, inp.args, run.signature?.params) : inputId}</span>
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
  compatible,
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
  compatible: boolean;
  onSelect: () => void;
  onHover: (id: string | null) => void;
}) {
  const count = optionCount(run.clusters, opt);
  const share = total ? count / total : 0;
  const assumption = q.kind === "assumption";
  const alt = !!opt.is_alternative;
  const custom = !!opt.is_custom;
  const incompatibleMsg = "No implementation does this together with your other answers";
  return (
    <label
      className={`group relative flex h-full cursor-pointer flex-col rounded-2xl border p-4 transition-[border-color,background-color,box-shadow,opacity] duration-200 ${
        selected
          ? "border-fog-100/80 bg-white/[0.07] shadow-[0_0_0_1px_rgba(231,236,245,0.5),0_12px_30px_-16px_rgba(165,180,252,0.5)]"
          : "border-white/10 bg-white/[0.02] hover:border-white/25 hover:bg-white/[0.04]"
      } ${readOnly && !selected ? "opacity-45" : ""} ${!readOnly && !selected && !compatible ? "opacity-55" : ""} ${
        alt && !selected ? "border-dashed" : ""
      } ${readOnly ? "cursor-default" : ""} has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent`}
      onMouseEnter={() => opt.cluster_ids.length === 1 && onHover(opt.cluster_ids[0])}
      onMouseLeave={() => onHover(null)}
      title={!compatible ? incompatibleMsg : undefined}
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
        <span className="text-[16px] font-semibold leading-snug text-fog-50">
          {assumption && !custom && (
            <span className={`mr-1.5 font-display text-[13px] font-bold uppercase tracking-wider ${alt ? "text-warn" : "text-add"}`}>
              {alt ? "Change to:" : "Keep:"}
            </span>
          )}
          {opt.label}
        </span>
      </div>
      {custom && (
        <span className="mt-2.5 inline-flex w-fit items-center gap-1.5 rounded-full border border-accent/35 bg-accent/10 px-2.5 py-0.5 text-[12px] font-semibold text-accent-strong">
          <IconCheck size={12} strokeWidth={2.8} /> Your answer · executed
        </span>
      )}
      {custom ? (
        opt.examples.length > 0 ? (
          <div className="mt-3 space-y-1 rounded-xl bg-ink-950/60 px-3 py-2.5">
            {opt.examples.map((ex) => (
              <Witness key={ex.input_id} run={run} inputId={ex.input_id} value={ex.value_repr} />
            ))}
          </div>
        ) : null
      ) : alt ? (
        <div className="mt-3 rounded-xl border border-dashed border-warn/30 bg-warn/[0.04] px-3 py-2.5">
          <div className="mb-1 text-[11.5px] font-semibold uppercase tracking-wider text-warn/90">Proposed, not executed</div>
          {opt.note ? (
            <div className="mono break-words text-[13.5px] leading-relaxed text-fog-200">{opt.note}</div>
          ) : (
            <div className="text-[13.5px] text-fog-400">No example given.</div>
          )}
        </div>
      ) : opt.examples.length > 0 ? (
        <div className="mt-3 space-y-1 rounded-xl bg-ink-950/60 px-3 py-2.5">
          {opt.examples.map((ex) => (
            <Witness key={ex.input_id} run={run} inputId={ex.input_id} value={ex.value_repr} />
          ))}
        </div>
      ) : assumption ? (
        <p className="mt-3 text-[13.5px] text-fog-400">What the implementations already do.</p>
      ) : null}
      {!compatible && !readOnly && (
        <p className="mt-2.5 flex items-start gap-1.5 text-[13px] leading-snug text-warn">
          <IconAlert size={14} className="mt-0.5 shrink-0" />
          {incompatibleMsg}
        </p>
      )}
      {custom ? (
        <div className="mt-auto pt-3.5 text-[13.5px] text-fog-400">
          A reference implementation was written from your words and run on every probe.
        </div>
      ) : alt ? (
        <div className="mt-auto pt-3.5 text-[13.5px] text-fog-400">
          No implementation does this yet. Locked tests will skip the affected cases.
        </div>
      ) : (
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
      )}
    </label>
  );
}

/** "Other…": the user describes the behaviour in their own words (sent as `other[qid]`, 3..300 chars). */
function OtherCard({
  q,
  text,
  readOnly,
  onSelect,
  onChange,
}: {
  q: Question;
  /** undefined = not selected. */
  text: string | undefined;
  readOnly: boolean;
  onSelect: () => void;
  onChange: (t: string) => void;
}) {
  const selected = text !== undefined;
  const len = text?.trim().length ?? 0;
  const tooShort = selected && len > 0 && len < OTHER_MIN;
  const taId = `other-${q.id}`;
  return (
    <div
      className={`flex h-full flex-col rounded-2xl border p-4 transition-[border-color,background-color] duration-200 ${
        selected ? "border-fog-100/80 bg-white/[0.07]" : "border-dashed border-white/15 bg-white/[0.015] hover:border-white/30"
      } has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent`}
    >
      <label className={`flex items-start gap-3 ${readOnly ? "cursor-default" : "cursor-pointer"}`}>
        <input
          type="radio"
          className="sr-only"
          name={`q-${q.id}`}
          value="__other"
          checked={selected}
          disabled={readOnly && !selected}
          onChange={() => !readOnly && onSelect()}
        />
        <span
          className={`mt-0.5 flex h-[20px] w-[20px] shrink-0 items-center justify-center rounded-full border-2 transition-colors ${
            selected ? "border-fog-50 bg-fog-50 text-ink-900" : "border-fog-500"
          }`}
          aria-hidden
        >
          {selected && <IconCheck size={12} strokeWidth={3} />}
        </span>
        <span>
          <span className="text-[16px] font-semibold leading-snug text-fog-50">Other…</span>
          <span className="mt-0.5 block text-[13.5px] text-fog-400">None of these? Say what you want instead.</span>
        </span>
      </label>
      {selected && (
        <div className="mt-3">
          <label htmlFor={taId} className="sr-only">
            Describe the behaviour you want
          </label>
          <textarea
            id={taId}
            value={text}
            readOnly={readOnly}
            autoFocus={!readOnly && !text}
            maxLength={OTHER_MAX}
            rows={3}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Describe the behaviour you want"
            aria-invalid={tooShort}
            aria-describedby={`${taId}-help`}
            className="block w-full resize-y rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2.5 text-[14.5px] leading-relaxed text-fog-50 placeholder:text-fog-500/70 focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/25 aria-[invalid=true]:border-warn/50"
          />
          <p id={`${taId}-help`} className={`mt-1.5 flex justify-between gap-2 text-[12.5px] ${tooShort ? "text-warn" : "text-fog-500"}`}>
            <span>
              {tooShort
                ? `At least ${OTHER_MIN} characters.`
                : "A reference implementation is written from your words and executed on every probe."}
            </span>
            <span className="tabular-nums">
              {text?.length ?? 0}/{OTHER_MAX}
            </span>
          </p>
        </div>
      )}
    </div>
  );
}

export function QuestionCard({
  run,
  q,
  idx,
  answer,
  answers,
  otherText,
  readOnly,
  styles,
  onAnswer,
  onOther,
  onHover,
}: {
  run: Run;
  q: Question;
  idx: number;
  answer?: string;
  /** All current selections, used for compatibility hints. */
  answers: Record<string, string>;
  /** Free-text answer; undefined when "Other…" isn't selected. */
  otherText?: string;
  readOnly: boolean;
  styles: Record<string, ClusterStyle>;
  onAnswer: (optId: string) => void;
  /** Select "Other…" / edit its text (clears any selected option). */
  onOther?: (text: string) => void;
  onHover: (id: string | null) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const assumption = q.kind === "assumption";
  const total = run.implementations.length;
  const chosen = q.options.find((o) => o.id === answer);
  const showOther = !!onOther && (!readOnly || otherText !== undefined);
  const nCards = q.options.length + (showOther ? 1 : 0);
  const cols = nCards === 4 ? "md:grid-cols-2 2xl:grid-cols-4" : nCards >= 3 ? "lg:grid-cols-3" : "md:grid-cols-2";
  const compact = readOnly && !!chosen && !expanded;
  const answered = !!chosen || otherValid(otherText);
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
            answered ? "bg-fog-100 text-ink-900" : "bg-white/[0.07] text-fog-200"
          }`}
        >
          {answered ? <IconCheck size={17} strokeWidth={2.6} /> : `${assumption ? "A" : "Q"}${idx + 1}`}
        </span>
        <div className="min-w-0">
          {assumption && typeof q.agree_count === "number" && (
            <span className="mb-1.5 inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-0.5 text-[12.5px] font-semibold text-fog-300">
              <span className="h-1.5 w-1.5 rounded-full bg-add" aria-hidden />
              {q.agree_count} of {total} implementations assumed this
            </span>
          )}
          <h3 id={`q-${q.id}-text`} className="font-display text-[21px] font-semibold leading-snug text-fog-50 sm:text-[23px]">
            {q.text}
          </h3>
          <p className="mt-1.5 max-w-[900px] text-[15px] leading-relaxed text-fog-400">
            <span className="font-semibold text-fog-300">Why it matters: </span>
            {q.why}
          </p>
        </div>
      </div>
      {compact ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-fog-100/30 bg-white/[0.04] px-4 py-3 sm:ml-[52px]">
          <span className="flex items-center gap-2.5 text-[16px] font-semibold text-fog-50">
            <IconCheck size={16} strokeWidth={2.6} className="text-add" />
            {assumption && !chosen!.is_custom && (
              <span className={chosen!.is_alternative ? "text-warn" : "text-add"}>{chosen!.is_alternative ? "Change to:" : "Keep:"}</span>
            )}
            {chosen!.label}
          </span>
          <span className="flex items-center gap-3 text-[13.5px] text-fog-400">
            {chosen!.is_custom ? (
              <span className="rounded-full border border-accent/35 bg-accent/10 px-2.5 py-0.5 text-[12px] font-semibold text-accent-strong">
                Your answer · executed
              </span>
            ) : chosen!.is_alternative ? (
              "proposed, not executed"
            ) : (
              `chosen by ${optionCount(run.clusters, chosen!)} of ${total}`
            )}
            <button type="button" className="btn btn-quiet py-1 text-[13px]" onClick={() => setExpanded(true)} aria-expanded={false}>
              Show all {q.options.length} options
            </button>
          </span>
          {chosen!.is_custom && chosen!.examples.length > 0 && (
            <div className="w-full space-y-1 rounded-lg bg-ink-950/60 px-3 py-2">
              {chosen!.examples.map((ex) => (
                <Witness key={ex.input_id} run={run} inputId={ex.input_id} value={ex.value_repr} />
              ))}
            </div>
          )}
        </div>
      ) : (
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
            compatible={optionCompatible(run.questions, answers, q, opt)}
            onSelect={() => onAnswer(opt.id)}
            onHover={onHover}
          />
        ))}
        {showOther && (
          <OtherCard
            q={q}
            text={otherText}
            readOnly={readOnly}
            onSelect={() => onOther!(otherText ?? "")}
            onChange={(t) => onOther!(t)}
          />
        )}
      </div>
      )}
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
                    {o.label} · {optionCount(run.clusters, o)} impl.
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
  const a = assumptionQuestions(run.questions).length;
  const executed = run.implementations.filter((i) => i.status === "executed").length;
  const consensusOnAssumptions = k <= 1 && a > 0;
  const toSettle = answerableQuestions(run.questions).length;
  return (
    <div>
      <p className="eyebrow">Result</p>
      <h2 className="mt-1 font-display text-[32px] font-bold leading-tight tracking-[-0.02em] text-fog-50 sm:text-[40px]">
        {consensusOnAssumptions ? (
          <>
            Every implementation agrees,{" "}
            <span className="text-accent-strong">but on assumptions you never stated.</span>
          </>
        ) : (
          <>
            Your spec has <span className="text-accent-strong">{k}</span> meaning{k === 1 ? "" : "s"}.
          </>
        )}
      </h2>
      <p className="mt-2 max-w-[860px] text-[16px] leading-relaxed text-fog-300">
        {executed} implementations ran on {run.inputs.length} probe inputs and split into {k} distinct behaviour
        {k === 1 ? "" : "s"}
        {crash ? ` (plus ${crash} that crash${crash === 1 ? "es" : ""})` : ""}.{" "}
        {toSettle > 0 ? (
          <>
            {q > 0 && <>{q === 1 ? "One question" : `${q} questions`} about where they disagree</>}
            {q > 0 && a > 0 && " and "}
            {a > 0 && (
              <>
                {q > 0 ? (a === 1 ? "one silent assumption" : `${a} silent assumptions`) : a === 1 ? "One silent assumption" : `${a} silent assumptions`} they all made
              </>
            )}
            {q + a === 1 ? " settles it." : " settle it."}
          </>
        ) : (
          "No ambiguities found: every implementation agrees."
        )}
      </p>
    </div>
  );
}

export function AssumptionsIntro({ count }: { count: number }) {
  return (
    <div className="pt-2">
      <p className="eyebrow">Silent assumptions</p>
      <h2 className="mt-1 font-display text-[24px] font-semibold text-fog-50 sm:text-[28px]">
        {count === 1 ? "One decision nobody asked you about" : `${count} decisions nobody asked you about`}
      </h2>
      <p className="mt-1.5 max-w-[860px] text-[15.5px] leading-relaxed text-fog-400">
        Every implementation agreed here, but your spec never said so. Keep the assumption, or change it. A change
        is written into the clarified spec and the affected cases are left out of the locked tests.
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
  recordedOnForkLive,
}: {
  answered: number;
  total: number;
  busy: boolean;
  locked: boolean;
  error: string | null;
  onLock: () => void;
  /** Set for recorded sample runs (server rejects answers): offer a live fork instead. */
  recordedOnForkLive?: () => void;
}) {
  if (recordedOnForkLive && !locked) {
    return (
      <div className="sticky bottom-4 z-20">
        <div className="card flex items-center justify-between gap-3 border-accent/25 bg-ink-800/95 px-4 py-3 sm:px-5 sm:py-4">
          <span className="text-[15px] text-fog-300">
            <span className="font-semibold text-fog-50">Recorded run.</span> Explore the options here, then fork it live
            to lock in your own answers.
          </span>
          <button type="button" className="btn btn-primary shrink-0 px-4 py-2.5 text-[15px] sm:px-6 sm:py-3 sm:text-[16px]" onClick={recordedOnForkLive}>
            Fork it live
          </button>
        </div>
      </div>
    );
  }
  const ready = answered === total;
  return (
    <div className="sticky bottom-4 z-20">
      <div className="card flex items-center justify-between gap-3 border-white/12 bg-ink-800/95 px-4 py-3 sm:px-5 sm:py-4">
        <div className="flex items-center gap-3">
          <div className="hidden gap-1 sm:flex" aria-hidden>
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
                answered{ready ? (total ? ": ready to lock in" : ". Nothing to decide") : ""}
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
          <button type="button" className="btn btn-primary shrink-0 px-4 py-2.5 text-[15px] sm:px-6 sm:py-3 sm:text-[16px]" disabled={!ready || busy} onClick={onLock}>
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
