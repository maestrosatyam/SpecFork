import { motion } from "framer-motion";
import type { ClusterStyle } from "../lib/clusters";
import { formatPct } from "../lib/format";
import type { Cluster, Implementation } from "../types";
import { IconCheck, IconCode, IconLock, IconX } from "./Icons";

export type Focus = { active: Set<string> | null; hover: string | null };

export function isDimmed(impl: Implementation, focus: Focus): boolean {
  if (focus.hover) return impl.cluster_id !== focus.hover;
  if (!focus.active) return false;
  return !impl.cluster_id || !focus.active.has(impl.cluster_id);
}

function tileLabel(impl: Implementation, style?: ClusterStyle): string {
  const n = `Implementation #${impl.index + 1}`;
  if (impl.status === "rejected") return `${n}: rejected, ${impl.reject_reason ?? "failed static check"}`;
  if (impl.status === "pending") return `${n}: being written`;
  if (impl.status === "generated") return `${n}: written, waiting to run`;
  if (impl.status === "error") return `${n}: execution error`;
  if (style) return `${n}: cluster ${style.label}${style.crash ? " (crashes)" : ""}`;
  return `${n}: executed`;
}

export function ImplTile({
  impl,
  style,
  dimmed,
  onOpen,
}: {
  impl: Implementation;
  style?: ClusterStyle;
  dimmed: boolean;
  onOpen: (impl: Implementation) => void;
}) {
  const clustered = !!style && impl.status === "executed";
  const base =
    "group relative flex aspect-square w-full flex-col items-center justify-center overflow-hidden rounded-[10px] border text-[11px] transition-[opacity,filter,transform,box-shadow] duration-300 hover:-translate-y-0.5 hover:shadow-[0_8px_18px_-10px_rgba(0,0,0,0.8)]";
  let cls = "";
  let bg: React.CSSProperties = {};
  let inner: React.ReactNode = null;
  switch (true) {
    case impl.status === "pending":
      cls = "border-dashed border-white/15 bg-white/[0.015] shimmer";
      break;
    case impl.status === "generated":
      cls = "border-white/20 bg-white/[0.06] text-fog-300";
      inner = <IconCode size={18} />;
      break;
    case impl.status === "rejected":
      cls = "border-white/10 bg-[#2a3047] text-fog-400";
      inner = <IconLock size={17} />;
      break;
    case impl.status === "error":
      cls = "border-danger/50 bg-danger/10 text-danger";
      inner = <IconX size={17} />;
      break;
    case clustered && style!.crash:
      cls = "stripes border-white/10 text-white";
      inner = <span className="rounded bg-ink-950/70 px-1.5 font-display text-[15px] font-bold leading-tight">{style!.label}</span>;
      break;
    case clustered:
      cls = "border-white/10 text-ink-950";
      bg = { backgroundColor: style!.color };
      inner = <span className="font-display text-[19px] font-bold leading-none">{style!.label}</span>;
      break;
    default:
      cls = "border-fog-300/30 bg-fog-300/15 text-fog-100";
      inner = <IconCheck size={17} />;
  }
  return (
    <motion.button
      type="button"
      layout="position"
      onClick={() => onOpen(impl)}
      disabled={impl.status === "pending"}
      aria-label={tileLabel(impl, style)}
      title={tileLabel(impl, style)}
      className={`${base} ${cls} ${dimmed ? "opacity-[0.18] saturate-[0.3]" : "opacity-100"} disabled:cursor-default`}
      style={bg}
      initial={false}
      animate={{ scale: 1 }}
      whileTap={{ scale: 0.96 }}
    >
      <span
        className={`absolute left-1.5 top-1 font-mono text-[10.5px] tabular-nums ${
          clustered && !style!.crash ? "text-ink-950/70" : "text-fog-500"
        }`}
      >
        {String(impl.index + 1).padStart(2, "0")}
      </span>
      {inner}
    </motion.button>
  );
}

export function ImplGrid({
  impls,
  styles,
  focus,
  onOpen,
  expected,
}: {
  impls: Implementation[];
  styles: Record<string, ClusterStyle>;
  focus: Focus;
  onOpen: (impl: Implementation) => void;
  expected: number;
}) {
  // Before fan-out starts we know n_samples but have no impls: render placeholders.
  const placeholders = impls.length === 0 ? Array.from({ length: expected }, (_, i) => i) : [];
  return (
    <div
      className="grid grid-cols-6 gap-2 sm:grid-cols-8 sm:gap-2.5 xl:grid-cols-12"
      role="list"
      aria-label="Independent implementations"
    >
      {impls.map((impl) => (
        <div role="listitem" key={impl.id}>
          <ImplTile
            impl={impl}
            style={impl.cluster_id ? styles[impl.cluster_id] : undefined}
            dimmed={isDimmed(impl, focus)}
            onOpen={onOpen}
          />
        </div>
      ))}
      {placeholders.map((i) => (
        <div role="listitem" key={`ph-${i}`} aria-label="Waiting for fan-out">
          <div className="aspect-square w-full rounded-[10px] border border-dashed border-white/[0.08] bg-white/[0.01]" />
        </div>
      ))}
    </div>
  );
}

export function GridStatusLegend() {
  const item = (el: React.ReactNode, text: string) => (
    <span className="inline-flex items-center gap-1.5">
      {el}
      {text}
    </span>
  );
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-[13px] text-fog-400">
      {item(<span className="h-3 w-3 rounded-[3px] border border-dashed border-white/25" />, "writing")}
      {item(<span className="h-3 w-3 rounded-[3px] border border-white/25 bg-white/10" />, "written")}
      {item(<span className="h-3 w-3 rounded-[3px] bg-fog-300/30" />, "executed")}
      {item(<span className="stripes h-3 w-3 rounded-[3px]" />, "crashes")}
      {item(
        <span className="flex h-3 w-3 items-center justify-center rounded-[3px] bg-[#2a3047] text-fog-400">
          <IconLock size={9} />
        </span>,
        "rejected by safety check",
      )}
    </div>
  );
}

export function ClusterLegend({
  clusters,
  styles,
  onHover,
  focus,
}: {
  clusters: Cluster[];
  styles: Record<string, ClusterStyle>;
  onHover: (id: string | null) => void;
  focus: Focus;
}) {
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Behaviour clusters">
      {clusters.map((c) => {
        const s = styles[c.id];
        const dim = focus.active ? !focus.active.has(c.id) : false;
        return (
          <li key={c.id}>
            <button
              type="button"
              onMouseEnter={() => onHover(c.id)}
              onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(c.id)}
              onBlur={() => onHover(null)}
              className={`chip transition-opacity ${dim ? "opacity-40" : ""} hover:border-white/25`}
              aria-label={`Cluster ${c.label}: ${c.size} implementations, ${formatPct(c.share)}${c.kind === "crash" ? ", crashes" : ""}`}
            >
              <span
                className={`h-3 w-3 rounded-[3px] ${s?.crash ? "stripes" : ""}`}
                style={s?.crash ? undefined : { background: s?.color }}
                aria-hidden
              />
              <span className="font-display font-semibold text-fog-50">{c.label}</span>
              <span className="tabular-nums">
                {c.size} · {formatPct(c.share)}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
