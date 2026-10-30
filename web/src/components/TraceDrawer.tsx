// Lazy-loaded (see RunView): the full call table is only needed when the drawer opens.
import { AnimatePresence, motion } from "framer-motion";
import { Fragment, useMemo, useState } from "react";
import { formatCost, formatDuration, formatTokens } from "../lib/format";
import { modelLabel, useLabels } from "../lib/models";
import type { CallRecord, Run } from "../types";
import { IconBrain, IconChevron } from "./Icons";
import { Drawer } from "./Overlay";
import { Stat } from "./Trace";

function Waterfall({ c, t0, span }: { c: CallRecord; t0: number; span: number }) {
  const left = ((c.started_at - t0) / span) * 100;
  const width = Math.max(0.8, (c.latency_s / span) * 100);
  return (
    <div className="relative h-2 w-full min-w-[120px] rounded-full bg-white/[0.05]" aria-hidden>
      <div
        className={`absolute top-0 h-2 rounded-full ${c.ok ? (c.thinking ? "bg-accent" : "bg-[#56B4E9]") : "bg-danger"}`}
        style={{ left: `${Math.max(0, Math.min(99, left))}%`, width: `${Math.min(100 - left, width)}%` }}
      />
    </div>
  );
}

export default function TraceDrawer({ run, open, onClose }: { run: Run; open: boolean; onClose: () => void }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState<"all" | "deep" | "fast">("all");
  const labels = useLabels();
  const m = run.metrics;
  const calls = run.trace;
  const { t0, span } = useMemo(() => {
    if (!calls.length) return { t0: 0, span: 1 };
    const t0 = Math.min(...calls.map((c) => c.started_at));
    const t1 = Math.max(...calls.map((c) => c.started_at + c.latency_s));
    return { t0, span: Math.max(0.001, t1 - t0) };
  }, [calls]);
  const byModel = useMemo(() => {
    const map = new Map<string, { calls: number; tokens: number; cost: number; latency: number }>();
    for (const c of calls) {
      const e = map.get(c.model) ?? { calls: 0, tokens: 0, cost: 0, latency: 0 };
      e.calls++;
      e.tokens += c.prompt_tokens + c.completion_tokens;
      e.cost += c.cost_usd;
      e.latency += c.latency_s;
      map.set(c.model, e);
    }
    return [...map.entries()];
  }, [calls]);
  const rows = calls
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => filter === "all" || (filter === "deep" ? c.model === run.settings.deep_model : c.model !== run.settings.deep_model));
  const toggle = (i: number) =>
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(i)) n.delete(i);
      else n.add(i);
      return n;
    });

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={1080}
      title="Under the hood"
      subtitle={`Every ${labels.family} call this run made on ${labels.provider}, with real latency, token counts and estimated cost.`}
    >
      <div className="grid grid-cols-2 gap-4 rounded-2xl border border-white/[0.07] bg-white/[0.02] p-5 sm:grid-cols-4">
        <Stat big label="Total cost" value={formatCost(m.total_cost_usd)} />
        <Stat
          big
          label="Tokens"
          value={formatTokens(m.prompt_tokens + m.completion_tokens)}
          sub={`${formatTokens(m.prompt_tokens)} in · ${formatTokens(m.completion_tokens)} out`}
        />
        <Stat big label="Calls" value={String(m.n_calls)} />
        <Stat big label="Wall time" value={formatDuration(m.wall_time_s)} />
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {byModel.map(([model, e]) => (
          <div key={model} className="rounded-xl border border-white/[0.07] px-4 py-3">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-fog-50">{modelLabel(model, labels)}</span>
              <span className="text-[13px] tabular-nums text-fog-400">{formatCost(e.cost)}</span>
            </div>
            <div className="mono mt-0.5 truncate text-[12.5px] text-fog-500">{model}</div>
            <div className="mt-1 text-[13.5px] tabular-nums text-fog-300">
              {e.calls} calls · {formatTokens(e.tokens)} tokens · avg {formatDuration(e.latency / e.calls)}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <h3 className="eyebrow">Calls ({rows.length})</h3>
        <div className="flex rounded-lg border border-white/10 p-0.5 text-[13px]" role="radiogroup" aria-label="Filter calls by model">
          {(["all", "deep", "fast"] as const).map((f) => (
            <button
              key={f}
              type="button"
              role="radio"
              aria-checked={filter === f}
              onClick={() => setFilter(f)}
              className={`rounded-md px-3 py-1 capitalize ${filter === f ? "bg-fog-100 font-semibold text-ink-900" : "text-fog-400 hover:text-fog-100"}`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {calls.length === 0 ? (
        <p className="mt-6 rounded-xl border border-dashed border-white/10 p-6 text-center text-fog-400">No calls yet. They'll appear here as the run progresses.</p>
      ) : (
        <div className="mt-3 overflow-x-auto rounded-xl border border-white/[0.07]">
          <table className="w-full min-w-[860px] text-left text-[14px]">
            <thead className="bg-white/[0.03] text-[12px] uppercase tracking-wider text-fog-400">
              <tr>
                <th className="w-10 px-3 py-2.5 font-semibold">#</th>
                <th className="px-3 py-2.5 font-semibold">Purpose</th>
                <th className="px-3 py-2.5 font-semibold">Model</th>
                <th className="px-3 py-2.5 font-semibold">Thinking</th>
                <th className="px-3 py-2.5 text-right font-semibold">Latency</th>
                <th className="px-3 py-2.5 text-right font-semibold">Tokens in/out</th>
                <th className="px-3 py-2.5 text-right font-semibold">Cost</th>
                <th className="w-[160px] px-3 py-2.5 font-semibold">Timeline</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ c, i }) => {
                const isOpen = expanded.has(i);
                const hasDetail = !!c.reasoning_excerpt || !!c.error || !!c.request_id;
                return (
                  <Fragment key={i}>
                    <tr className={`border-t border-white/[0.05] ${hasDetail ? "cursor-pointer hover:bg-white/[0.025]" : ""}`} onClick={() => hasDetail && toggle(i)}>
                      <td className="px-3 py-2 tabular-nums text-fog-500">{i + 1}</td>
                      <td className="px-3 py-2">
                        <span className="flex items-center gap-1.5">
                          {hasDetail ? (
                            <button
                              type="button"
                              aria-expanded={isOpen}
                              aria-label={`${isOpen ? "Hide" : "Show"} details for ${c.purpose}`}
                              className="rounded p-0.5 text-fog-400 hover:text-fog-50"
                              onClick={(e) => {
                                e.stopPropagation();
                                toggle(i);
                              }}
                            >
                              <IconChevron size={14} className={`transition-transform ${isOpen ? "rotate-90" : ""}`} />
                            </button>
                          ) : (
                            <span className="w-[18px]" />
                          )}
                          <span className="text-fog-100">{c.purpose}</span>
                          {!c.ok && <span className="rounded bg-danger/15 px-1.5 text-[11.5px] font-semibold text-danger">failed</span>}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-[13px] text-fog-300" title={c.model}>
                        {modelLabel(c.model, labels)}
                      </td>
                      <td className="px-3 py-2">
                        {c.thinking ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-accent/15 px-2 py-0.5 text-[12px] font-semibold text-accent-strong">
                            <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden /> on
                          </span>
                        ) : (
                          <span className="text-[12.5px] text-fog-500">off</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-fog-200">{formatDuration(c.latency_s)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-fog-300">
                        {c.prompt_tokens.toLocaleString()} / {c.completion_tokens.toLocaleString()}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-fog-200">{formatCost(c.cost_usd)}</td>
                      <td className="px-3 py-2">
                        <Waterfall c={c} t0={t0} span={span} />
                      </td>
                    </tr>
                    <AnimatePresence initial={false}>
                      {isOpen && (
                        <tr className="bg-ink-950/50">
                          <td />
                          <td colSpan={7} className="px-3 pb-4 pt-1">
                            <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                              {c.reasoning_excerpt && (
                                <>
                                  <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wider text-accent">
                                    <IconBrain size={14} /> {modelLabel(c.model, labels)} reasoning (excerpt)
                                  </div>
                                  <blockquote className="mono max-w-[860px] whitespace-pre-wrap border-l-2 border-accent/40 pl-3 text-[13px] leading-relaxed text-fog-300">
                                    {c.reasoning_excerpt}
                                  </blockquote>
                                </>
                              )}
                              {c.error && <p className="mono mt-2 text-[13px] text-danger">{c.error}</p>}
                              {c.request_id && <p className="mono mt-2 text-[12px] text-fog-500">request_id: {c.request_id}</p>}
                            </motion.div>
                          </td>
                        </tr>
                      )}
                    </AnimatePresence>
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-4 text-[12.5px] leading-relaxed text-fog-500">
        Costs are estimated from {labels.provider} list prices per million tokens. Reasoning excerpts are the first part
        of the model's <span className="mono">reasoning_content</span>, shown only for calls made with thinking enabled.
      </p>
    </Drawer>
  );
}
