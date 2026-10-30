import { formatCost, formatDuration, formatTokens, shortModel } from "../lib/format";
import { runModelLabels, useLabels } from "../lib/models";
import type { Run } from "../types";
import { IconChevron, IconTerminal } from "./Icons";

export function Stat({ label, value, big = false, sub }: { label: string; value: string; big?: boolean; sub?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[12px] font-medium uppercase tracking-wider text-fog-500">{label}</div>
      <div className={`font-display font-semibold tabular-nums text-fog-50 ${big ? "text-[26px]" : "text-[20px]"}`}>{value}</div>
      {sub && <div className="text-[12.5px] tabular-nums text-fog-400">{sub}</div>}
    </div>
  );
}

/** Compact always-visible card in the run's side rail. */
export function TraceSummary({ run, onOpen }: { run: Run; onOpen: () => void }) {
  const m = run.metrics;
  const thinking = run.trace.filter((c) => c.thinking).length;
  const labels = useLabels();
  const rl = runModelLabels(run, labels);
  return (
    <section className="rounded-2xl border border-white/[0.07] bg-white/[0.02] p-4" aria-labelledby="uth-h">
      <div className="flex items-center justify-between">
        <h2 id="uth-h" className="eyebrow flex items-center gap-2">
          <IconTerminal size={15} /> Under the hood
        </h2>
        <span className="text-[12px] text-fog-500">{labels.provider}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3">
        <Stat label="Calls" value={String(m.n_calls)} />
        <Stat label="Cost" value={formatCost(m.total_cost_usd)} />
        <Stat label="Tokens" value={formatTokens(m.prompt_tokens + m.completion_tokens)} />
        <Stat label="Wall time" value={formatDuration(m.wall_time_s)} />
      </div>
      <div className="mt-3 space-y-1 text-[13px] text-fog-400">
        <div className="flex justify-between gap-2">
          <span>Fast</span>
          <span className="truncate text-fog-200" title={run.settings.fast_model}>
            {rl.fast}
          </span>
        </div>
        <div className="flex justify-between gap-2">
          <span>Deep</span>
          <span className="truncate text-fog-200" title={run.settings.deep_model}>
            {rl.deep}
          </span>
        </div>
        <div className="mono truncate text-[11.5px] text-fog-500" title={`${run.settings.fast_model} · ${run.settings.deep_model}`}>
          {shortModel(run.settings.fast_model)} · {shortModel(run.settings.deep_model)}
        </div>
      </div>
      <button type="button" className="btn btn-ghost mt-4 w-full" onClick={onOpen}>
        Inspect {m.n_calls} calls{thinking ? ` · ${thinking} with reasoning` : ""}
        <IconChevron size={16} />
      </button>
    </section>
  );
}

