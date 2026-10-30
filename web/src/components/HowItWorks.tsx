import { DEFAULT_LABELS, useLabels, type Labels } from "../lib/models";
import { Modal } from "./Overlay";

/** Who does what: framing, fan-out and re-fork use the fast model; questions, assumptions and the clarified spec the deep one. */
export const howSteps = (l: Pick<Labels, "fast" | "deep"> = DEFAULT_LABELS) => [
  {
    n: "01",
    title: "Fork",
    body: `${l.fast} frames your one-line spec into a function signature and edge-case probe inputs, then writes N independent implementations of it.`,
    color: "#56B4E9",
  },
  {
    n: "02",
    title: "Execute & cluster",
    body: "Every implementation runs in a sandbox on every probe input. Implementations that behave identically are grouped together, and each group is one reading of your spec.",
    color: "#F5A524",
  },
  {
    n: "03",
    title: "Ask",
    body: `Each disagreement becomes a concrete witness, such as split_bill(100.0, 3) giving three different answers, and ${l.deep} turns it into a plain-English question. It also looks for silent assumptions every implementation made. Crashes are reported as likely bugs, not as meanings.`,
    color: "#2FC79E",
  },
  {
    n: "04",
    title: "Lock & re-fork",
    body: `${l.deep} writes your answers into a clarified spec; deterministic pytest tests and a reference implementation come with it. Re-fork the clarified spec on ${l.fast} to measure how many fresh implementations now match what you meant.`,
    color: "#E68AC0",
  },
];

export function HowItWorksSteps({ compact = false }: { compact?: boolean }) {
  const labels = useLabels();
  const steps = howSteps(labels);
  return (
    <ol className={`grid gap-4 ${compact ? "sm:grid-cols-2 xl:grid-cols-4" : "sm:grid-cols-2"}`}>
      {steps.map((s) => (
        <li key={s.n} className="relative overflow-hidden rounded-2xl border border-white/[0.07] bg-white/[0.02] p-5">
          <div className="absolute inset-x-0 top-0 h-[3px]" style={{ background: s.color }} aria-hidden />
          <div className="flex items-baseline gap-3">
            <span className="font-display text-[14px] font-semibold tabular-nums" style={{ color: s.color }}>
              {s.n}
            </span>
            <h3 className="font-display text-[19px] font-semibold text-fog-50">{s.title}</h3>
          </div>
          <p className="mt-2 text-[15px] leading-relaxed text-fog-300">{s.body}</p>
        </li>
      ))}
    </ol>
  );
}

export function HowItWorksModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const labels = useLabels();
  return (
    <Modal open={open} onClose={onClose} title="How SpecFork works">
      <p className="mb-6 max-w-[760px] text-[16px] leading-relaxed text-fog-300">
        A coding agent that gets an ambiguous spec quietly picks one meaning. SpecFork asks many independent
        implementations at once and runs them, so every hidden choice shows up as different behaviour. Each
        difference is shown as a concrete input that you can settle.
      </p>
      <HowItWorksSteps />
      <p className="mt-6 text-[13.5px] text-fog-500">
        All model calls go to {labels.family} models on {labels.provider}: {labels.fast} for framing, fan-out and
        re-forks; {labels.deep} for questions, silent assumptions and the clarified spec. The <em>Under the hood</em> panel on
        every run lists each call with its model, latency, token count and cost.
      </p>
    </Modal>
  );
}
