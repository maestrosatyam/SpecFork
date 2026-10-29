import { Modal } from "./Overlay";

export const HOW_STEPS = [
  {
    n: "01",
    title: "Fork",
    body: "Nemotron 3 Ultra frames your one-line spec into a function signature and edge-case probe inputs. Then Nemotron 3.5 Lightning writes N independent implementations of it.",
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
    body: "Each disagreement becomes a concrete witness, such as split_bill(100.0, 3) giving three different answers, and Nemotron 3 Ultra turns it into a plain-English question. Crashes are reported as likely bugs, not as meanings.",
    color: "#2FC79E",
  },
  {
    n: "04",
    title: "Lock & re-fork",
    body: "Your answers produce a clarified spec, deterministic pytest tests and a reference implementation. Re-fork the clarified spec to measure how many fresh implementations now match what you meant.",
    color: "#E68AC0",
  },
];

export function HowItWorksSteps({ compact = false }: { compact?: boolean }) {
  return (
    <ol className={`grid gap-4 ${compact ? "sm:grid-cols-2 xl:grid-cols-4" : "sm:grid-cols-2"}`}>
      {HOW_STEPS.map((s) => (
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
  return (
    <Modal open={open} onClose={onClose} title="How SpecFork works">
      <p className="mb-6 max-w-[760px] text-[16px] leading-relaxed text-fog-300">
        A coding agent that gets an ambiguous spec quietly picks one meaning. SpecFork asks many independent
        implementations at once and runs them, so every hidden choice shows up as different behaviour. Each
        difference is shown as a concrete input that you can settle.
      </p>
      <HowItWorksSteps />
      <p className="mt-6 text-[13.5px] text-fog-500">
        All model calls go to NVIDIA Nemotron models on Nebius Token Factory. The <em>Under the hood</em> panel on
        every run lists each call with its model, latency, token count and cost.
      </p>
    </Modal>
  );
}
