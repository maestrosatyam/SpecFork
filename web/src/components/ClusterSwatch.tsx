import type { ClusterStyle } from "../lib/clusters";

export function ClusterSwatch({ style, size = 14 }: { style?: ClusterStyle; size?: number }) {
  if (!style) return null;
  return (
    <span
      className={`inline-block shrink-0 rounded-[4px] ${style.crash ? "stripes" : ""}`}
      style={{ width: size, height: size, background: style.crash ? undefined : style.color }}
      aria-hidden
    />
  );
}
