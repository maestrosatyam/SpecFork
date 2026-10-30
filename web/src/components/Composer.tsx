import { motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { ApiError, type Api } from "../api";
import { DEFAULT_SAMPLES, MAX_SPEC_CHARS, SAMPLE_COUNTS } from "../config";
import { formatDate, truncate } from "../lib/format";
import { DEFAULT_PROVIDER_LABEL, modelsForRole, useLabels } from "../lib/models";
import type { AvailableModel, CreateRunBody, Health, Preset, RunSummary } from "../types";
import { HowItWorksSteps } from "./HowItWorks";
import { IconAlert, IconArrowRight, IconChevron } from "./Icons";

type ErrorInfo = { title: string; body: string; tone: "warn" | "danger" };

export function describeCreateError(e: unknown, provider: string = DEFAULT_PROVIDER_LABEL): ErrorInfo {
  if (e instanceof ApiError) {
    if (e.status === 429)
      return {
        title: "Slow down a little: rate limit reached",
        body: `${e.detail} Live runs are rate-limited to keep the demo fair. Try again in a minute, or open a sample run below.`,
        tone: "warn",
      };
    if (e.status === 503)
      return {
        title: "Live inference isn't available right now",
        body: `${e.detail || `The server has no ${provider} key configured.`} You can still open a recorded sample run.`,
        tone: "warn",
      };
    if (e.status === 0) return { title: "Can't reach the server", body: e.detail, tone: "danger" };
    return { title: `Request failed (${e.status})`, body: e.detail, tone: "danger" };
  }
  return { title: "Something went wrong", body: e instanceof Error ? e.message : String(e), tone: "danger" };
}

export function validateSpec(spec: string): string | null {
  const t = spec.trim();
  if (!t) return "Write a one- or two-sentence description of the function you want.";
  if (t.length < 10) return "That's a bit short. Describe what the function should do.";
  if (spec.length > MAX_SPEC_CHARS) return `Keep it under ${MAX_SPEC_CHARS.toLocaleString()} characters (currently ${spec.length.toLocaleString()}).`;
  return null;
}

const HERO_ROWS = [
  { label: "A", color: "#56B4E9", out: "[33.34, 33.33, 33.33]", n: 12 },
  { label: "B", color: "#F5A524", out: "[33.33, 33.33, 33.33]", n: 6 },
  { label: "C", color: "#2FC79E", out: "[33.34, 33.34, 33.34]", n: 4 },
];

/** Tiny illustration of the core idea: one input, several defensible answers. */
function HeroExample() {
  return (
    <motion.figure
      className="card hidden p-5 xl:block"
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.5, delay: 0.15 }}
      aria-label="Example: three implementations of the same spec disagree"
    >
      <figcaption className="eyebrow">Same spec, same input</figcaption>
      <div className="mono mt-3 text-[15px] text-fog-100">
        split_bill(<span className="text-[#F5B86B]">100.0</span>, <span className="text-[#F5B86B]">3</span>)
      </div>
      <ul className="mt-3 space-y-2">
        {HERO_ROWS.map((r, i) => (
          <motion.li
            key={r.label}
            className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-ink-950/60 px-3 py-2.5"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.35 + i * 0.15 }}
          >
            <span
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md font-display text-[14px] font-bold text-ink-950"
              style={{ background: r.color }}
            >
              {r.label}
            </span>
            <span className="mono flex-1 text-[14px] text-fog-50">{r.out}</span>
            <span className="text-[12.5px] tabular-nums text-fog-400">{r.n} impl.</span>
          </motion.li>
        ))}
      </ul>
      <p className="mt-3 text-[13.5px] leading-snug text-fog-400">
        Three readings of “evenly, rounding to cents”, all plausible. SpecFork makes you pick one before your agent does.
      </p>
    </motion.figure>
  );
}

/** Default registry key for a role: the one whose label matches the health default, else the first. */
export function defaultModelKey(models: AvailableModel[], defaultLabel: string): string {
  return (models.find((m) => m.label === defaultLabel) ?? models[0])?.key ?? "";
}

function ModelSelect({
  id,
  label,
  hint,
  models,
  value,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  models: AvailableModel[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1">
      <span className="text-[13px] font-medium text-fog-300">
        {label} <span className="font-normal text-fog-500">· {hint}</span>
      </span>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-white/10 bg-ink-950/60 px-3 py-2 text-[14px] text-fog-100 focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/25"
      >
        {models.map((m) => (
          <option key={m.key} value={m.key}>
            {m.label}
            {m.provider_label ? ` (${m.provider_label})` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Composer({
  api,
  presets,
  presetsError,
  recent,
  onCreated,
  onOpenRun,
  initialSpec = "",
  liveDisabled = false,
  health = null,
}: {
  api: Api;
  presets: Preset[] | null;
  presetsError: string | null;
  recent: RunSummary[];
  onCreated: (id: string) => void;
  onOpenRun: (id: string) => void;
  initialSpec?: string;
  liveDisabled?: boolean;
  health?: Health | null;
}) {
  const labels = useLabels();
  const fastModels = modelsForRole(labels.available, "fast");
  const deepModels = modelsForRole(labels.available, "deep");
  const [fastKey, setFastKey] = useState(() => defaultModelKey(fastModels, labels.fast));
  const [deepKey, setDeepKey] = useState(() => defaultModelKey(deepModels, labels.deep));
  const [assumptions, setAssumptions] = useState(true);
  const [exceptionTypes, setExceptionTypes] = useState(false);
  const fastDefault = defaultModelKey(fastModels, labels.fast);
  const deepDefault = defaultModelKey(deepModels, labels.deep);
  const advancedChanged = !assumptions || exceptionTypes || (fastKey && fastKey !== fastDefault) || (deepKey && deepKey !== deepDefault);
  const [spec, setSpec] = useState(initialSpec);
  const [presetId, setPresetId] = useState<string | undefined>();
  const [n, setN] = useState<number>(DEFAULT_SAMPLES);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ErrorInfo | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    taRef.current?.focus();
  }, []);

  const validation = validateSpec(spec);
  const showValidation = touched && validation;
  const over = spec.length > MAX_SPEC_CHARS;

  const submit = async () => {
    setTouched(true);
    if (validation || busy) return;
    setBusy(true);
    setError(null);
    try {
      const matching = presets?.find((p) => p.id === presetId && p.spec.trim() === spec.trim());
      const body: CreateRunBody = { spec: spec.trim(), n_samples: n, preset_id: matching?.id, assumptions };
      if (exceptionTypes) body.exception_types = true;
      // Only send model keys the server advertised, and only when the user picked a non-default one.
      if (fastKey && fastKey !== fastDefault && fastModels.some((m) => m.key === fastKey)) body.fast_model = fastKey;
      if (deepKey && deepKey !== deepDefault && deepModels.some((m) => m.key === deepKey)) body.deep_model = deepKey;
      const { id } = await api.createRun(body);
      onCreated(id);
    } catch (e) {
      setError(describeCreateError(e, labels.provider));
      setBusy(false);
    }
  };

  const samples = recent.filter((r) => r.is_sample);
  const others = recent.filter((r) => !r.is_sample).slice(0, 4);

  return (
    <div className="mx-auto max-w-[1400px] px-4 pb-24 pt-10 sm:px-6 sm:pt-16 lg:px-10">
      <div className="grid items-center gap-10 xl:grid-cols-[minmax(0,1fr)_380px]">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
        <p className="eyebrow mb-4 flex items-center gap-2">
          <span className="inline-block h-px w-8 bg-fog-500/60" aria-hidden />
          Ambiguity finder for coding agents
        </p>
        <h1 className="font-display text-[34px] font-bold leading-[1.06] tracking-[-0.03em] text-fog-50 sm:text-[50px]">
          Your spec means more than one thing.
          <span className="block text-fog-400">Find out which, before your coding agent guesses.</span>
        </h1>
        <p className="chip mt-4 xl:hidden">
          <span className="h-1.5 w-1.5 rounded-full bg-[#76b900]" aria-hidden />
          Powered by {labels.family} on {labels.provider}
        </p>
        <p className="mt-5 max-w-[760px] text-[17px] leading-relaxed text-fog-300">
          SpecFork has {labels.fast} write a couple of dozen independent implementations of your spec, runs them all,
          and turns every disagreement into one concrete question. You answer, and you get a clarified spec, tests
          and a reference implementation.
        </p>
      </motion.div>

        <HeroExample />
      </div>

      <motion.form
        className="card mt-9 p-4 sm:p-6"
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.08 }}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        aria-label="Write a spec"
      >
        <div className="flex items-center justify-between gap-3">
          <label htmlFor="spec" className="eyebrow">
            Function spec
          </label>
          <span className={`mono text-[12.5px] tabular-nums ${over ? "text-danger" : "text-fog-500"}`} aria-live="polite">
            {spec.length.toLocaleString()} / {MAX_SPEC_CHARS.toLocaleString()}
          </span>
        </div>
        <textarea
          id="spec"
          ref={taRef}
          value={spec}
          onChange={(e) => {
            setSpec(e.target.value);
            setError(null);
          }}
          onBlur={() => spec && setTouched(true)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              submit();
            }
          }}
          rows={4}
          placeholder="e.g. Split a restaurant bill evenly among N people, rounding to cents."
          aria-invalid={!!showValidation}
          aria-describedby="spec-help"
          className="mono mt-3 block w-full resize-y rounded-xl border border-white/10 bg-ink-950/60 px-4 py-3.5 text-[17px] leading-relaxed text-fog-50 placeholder:text-fog-500/70 focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/25 aria-[invalid=true]:border-danger/60 sm:text-[18px]"
        />
        <p id="spec-help" className={`mt-2 min-h-[22px] text-[14px] ${showValidation ? "text-danger" : "text-fog-500"}`}>
          {showValidation ? validation : "One or two sentences, the way you'd brief a coding agent. Python function, pure inputs and outputs."}
        </p>

        <div className="mt-3">
          <div className="eyebrow mb-2.5">Try a preset</div>
          {presets === null && !presetsError && (
            <div className="flex gap-2" aria-label="Loading presets">
              {[0, 1, 2].map((i) => (
                <span key={i} className="shimmer h-[38px] w-40 rounded-full border border-white/[0.06] bg-white/[0.03]" />
              ))}
            </div>
          )}
          {presetsError && <p className="text-[14px] text-fog-500">Presets unavailable ({presetsError}).</p>}
          {presets && (
            <ul className="flex flex-wrap gap-2.5">
              {presets.map((p) => (
                <li key={p.id} className="flex items-stretch overflow-hidden rounded-full border border-white/10 bg-white/[0.03]">
                  <button
                    type="button"
                    onClick={() => {
                      setSpec(p.spec);
                      setPresetId(p.id);
                      setTouched(false);
                      setError(null);
                      taRef.current?.focus();
                    }}
                    className={`px-4 py-2 text-left text-[14.5px] transition-colors hover:bg-white/[0.06] ${
                      presetId === p.id && spec === p.spec ? "bg-white/[0.08] text-fog-50" : "text-fog-200"
                    }`}
                    title={p.spec}
                  >
                    <span className="font-medium text-fog-50">{p.title}</span>
                    <span className="ml-2 hidden text-fog-400 sm:inline">{p.tagline}</span>
                  </button>
                  {p.sample_run_id && (
                    <button
                      type="button"
                      onClick={() => onOpenRun(p.sample_run_id!)}
                      className="flex items-center gap-1 border-l border-white/10 px-3 text-[13px] font-medium text-accent transition-colors hover:bg-accent/10 hover:text-accent-strong"
                      aria-label={`View sample run: ${p.title}`}
                    >
                      View sample run <IconChevron size={14} />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="mt-6 flex flex-col gap-4 border-t border-white/[0.06] pt-5 sm:flex-row sm:items-center sm:justify-between">
          <fieldset className="flex items-center gap-3">
            <legend className="sr-only">Number of independent implementations</legend>
            <span className="text-[14.5px] text-fog-300" aria-hidden>
              Implementations
            </span>
            <div className="flex rounded-xl border border-white/10 bg-ink-950/50 p-1" role="radiogroup" aria-label="Number of implementations">
              {SAMPLE_COUNTS.map((c) => (
                <label key={c} className="relative">
                  <input
                    type="radio"
                    name="n_samples"
                    value={c}
                    checked={n === c}
                    onChange={() => setN(c)}
                    className="peer sr-only"
                  />
                  <span className="block cursor-pointer rounded-lg px-3.5 py-1.5 text-[14.5px] font-semibold tabular-nums text-fog-400 transition-colors peer-checked:bg-fog-100 peer-checked:text-ink-900 peer-focus-visible:outline-2 peer-focus-visible:outline-accent hover:text-fog-100 peer-checked:hover:text-ink-900">
                    {c}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <details className="group text-[14px] sm:mr-auto sm:ml-4">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-lg px-2 py-1.5 text-fog-400 hover:text-fog-100 [&::-webkit-details-marker]:hidden">
              <IconChevron size={14} className="transition-transform group-open:rotate-90" />
              Advanced
              {advancedChanged && <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-label="changed from defaults" />}
            </summary>
            <div className="mt-2 grid gap-3 rounded-xl border border-white/[0.07] bg-ink-950/40 p-3 sm:min-w-[340px]">
              {fastModels.length > 1 && (
                <ModelSelect
                  id="fast-model"
                  label="Fast model"
                  hint="framing, fan-out, re-fork"
                  models={fastModels}
                  value={fastKey}
                  onChange={setFastKey}
                />
              )}
              {deepModels.length > 1 && (
                <ModelSelect
                  id="deep-model"
                  label="Deep model"
                  hint="questions, assumptions, clarified spec"
                  models={deepModels}
                  value={deepKey}
                  onChange={setDeepKey}
                />
              )}
              <label className="flex cursor-pointer items-start gap-2.5">
                <input
                  type="checkbox"
                  checked={assumptions}
                  onChange={(e) => setAssumptions(e.target.checked)}
                  className="mt-0.5 h-4 w-4 accent-[#a5b4fc]"
                />
                <span>
                  <span className="text-fog-100">Look for silent assumptions</span>
                  <span className="block text-[12.5px] text-fog-500">
                    Also ask about choices every implementation made that your spec never stated.
                  </span>
                </span>
              </label>
              <label className="flex cursor-pointer items-start gap-2.5">
                <input
                  type="checkbox"
                  checked={exceptionTypes}
                  onChange={(e) => setExceptionTypes(e.target.checked)}
                  className="mt-0.5 h-4 w-4 accent-[#a5b4fc]"
                />
                <span>
                  <span className="text-fog-100">Distinguish exception types</span>
                  <span className="block text-[12.5px] text-fog-500">
                    Treat ValueError vs TypeError as different behaviours and lock the type in tests.
                  </span>
                </span>
              </label>
              {fastModels.length <= 1 && deepModels.length <= 1 && (
                <p className="text-[12.5px] text-fog-500">
                  Models: {labels.fast} (fast) · {labels.deep} (deep)
                  {health?.public_demo ? " · fixed on this public demo" : ""}
                </p>
              )}
            </div>
          </details>
          <button type="submit" className="btn btn-primary px-6 py-3 text-[16px]" disabled={busy || over}>
            {busy ? (
              <>
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-900/30 border-t-ink-900" aria-hidden />
                Forking…
              </>
            ) : (
              <>
                Fork it <IconArrowRight size={18} />
                <span className="kbd ml-1 hidden sm:inline">⌘/Ctrl ↵</span>
              </>
            )}
          </button>
        </div>

        {liveDisabled && !error && (
          <p className="mt-4 flex items-center gap-2 rounded-xl border border-warn/25 bg-warn/[0.06] px-4 py-3 text-[14.5px] text-fog-300">
            <IconAlert className="shrink-0 text-warn" size={18} />
            Live inference isn't configured on this server right now. Recorded sample runs still work.
          </p>
        )}
        {error && (
          <div
            role="alert"
            className={`mt-4 flex gap-3 rounded-xl border p-4 ${
              error.tone === "warn" ? "border-warn/30 bg-warn/[0.07]" : "border-danger/30 bg-danger/[0.07]"
            }`}
          >
            <IconAlert className={`mt-0.5 shrink-0 ${error.tone === "warn" ? "text-warn" : "text-danger"}`} size={20} />
            <div>
              <div className="font-semibold text-fog-50">{error.title}</div>
              <div className="mt-0.5 text-[14.5px] text-fog-300">{error.body}</div>
            </div>
          </div>
        )}
      </motion.form>

      {(samples.length > 0 || others.length > 0) && (
        <section className="mt-10" aria-labelledby="recent-h">
          <h2 id="recent-h" className="eyebrow mb-3">
            Recorded &amp; recent runs
          </h2>
          <ul className="grid gap-3 md:grid-cols-2">
            {[...samples, ...others].slice(0, 6).map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => onOpenRun(r.id)}
                  className="group flex w-full items-center gap-4 rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-3 text-left transition-colors hover:border-white/15 hover:bg-white/[0.05]"
                >
                  <span className="mono min-w-0 flex-1 truncate text-[14.5px] text-fog-100">{truncate(r.spec, 90)}</span>
                  <span className="shrink-0 text-[13px] text-fog-500">
                    {r.is_sample ? "sample" : formatDate(r.created_at)} · {r.n_clusters} clusters
                  </span>
                  <IconChevron size={16} className="shrink-0 text-fog-500 transition-transform group-hover:translate-x-0.5" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-14" aria-labelledby="how-h">
        <h2 id="how-h" className="eyebrow mb-4">
          How it works
        </h2>
        <HowItWorksSteps compact />
      </section>
    </div>
  );
}
