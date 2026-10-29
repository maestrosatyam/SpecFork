import type { ClusterStyle } from "../lib/clusters";
import { formatCall, shortModel } from "../lib/format";
import type { Implementation, Run } from "../types";
import { CodeBlock, CopyButton } from "./CodeBlock";
import { IconCheck, IconLock, IconX } from "./Icons";
import { Drawer } from "./Overlay";

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

export function ImplDrawer({
  run,
  impl,
  styles,
  onClose,
}: {
  run: Run;
  impl: Implementation | null;
  styles: Record<string, ClusterStyle>;
  onClose: () => void;
}) {
  const cluster = impl?.cluster_id ? run.clusters.find((c) => c.id === impl.cluster_id) : undefined;
  const style = impl?.cluster_id ? styles[impl.cluster_id] : undefined;
  const witnessIds = new Set(run.questions.flatMap((q) => q.witness_input_ids));
  const expected = new Map(run.resolution?.locked_cases.map((c) => [c.input_id, c.expected_repr]) ?? []);
  const fn = run.signature?.name;

  return (
    <Drawer
      open={!!impl}
      onClose={onClose}
      title={impl ? `Implementation #${String(impl.index + 1).padStart(2, "0")}` : ""}
      subtitle={
        impl && (
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="mono">{shortModel(impl.model)}</span>
            <span aria-hidden>·</span>
            <span>status: {impl.status}</span>
            {cluster && (
              <>
                <span aria-hidden>·</span>
                <span className="inline-flex items-center gap-1.5 text-fog-100">
                  <ClusterSwatch style={style} /> Cluster {cluster.label}
                  {cluster.kind === "crash" ? " (crashes)" : ""}
                </span>
              </>
            )}
          </span>
        )
      }
    >
      {impl && (
        <div className="space-y-6">
          {cluster?.summary && (
            <p className="rounded-xl border border-white/[0.07] bg-white/[0.03] px-4 py-3 text-[15px] leading-relaxed text-fog-200">
              <span className="font-semibold text-fog-50">Cluster {cluster.label}: </span>
              {cluster.summary}
            </p>
          )}
          {impl.status === "rejected" && (
            <div className="flex gap-3 rounded-xl border border-white/10 bg-[#2a3047]/60 px-4 py-3 text-[15px] text-fog-200">
              <IconLock className="mt-0.5 shrink-0 text-fog-400" />
              <div>
                <div className="font-semibold text-fog-50">Rejected before execution</div>
                {impl.reject_reason ?? "Failed the static safety check."}
              </div>
            </div>
          )}

          {impl.outcomes && (
            <section aria-labelledby="outcomes-h">
              <h3 id="outcomes-h" className="eyebrow mb-2.5">
                Outcomes on probe inputs
              </h3>
              <div className="overflow-x-auto rounded-xl border border-white/[0.07]">
                <table className="w-full min-w-[560px] text-left text-[14px]">
                  <thead className="bg-white/[0.03] text-[12.5px] uppercase tracking-wider text-fog-400">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold">Input</th>
                      <th className="px-4 py-2.5 font-semibold">Result</th>
                      {expected.size > 0 && <th className="px-4 py-2.5 text-center font-semibold">Matches intent</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {run.inputs.map((inp) => {
                      const o = impl.outcomes?.[inp.id];
                      const exp = expected.get(inp.id);
                      const match = o && exp !== undefined ? o.value_repr === exp : undefined;
                      return (
                        <tr key={inp.id} className="border-t border-white/[0.05] align-top">
                          <td className="mono px-4 py-2.5 text-fog-200">
                            {formatCall(fn, inp.args)}
                            <span className="ml-2 inline-flex gap-1 align-middle">
                              {witnessIds.has(inp.id) && (
                                <span className="rounded bg-accent/15 px-1.5 py-px font-sans text-[11px] font-semibold text-accent-strong">
                                  witness
                                </span>
                              )}
                              {inp.source === "fuzz" && (
                                <span className="rounded bg-white/[0.06] px-1.5 py-px font-sans text-[11px] text-fog-400">fuzz</span>
                              )}
                            </span>
                          </td>
                          <td className="mono px-4 py-2.5">
                            {!o ? (
                              <span className="text-fog-500">–</span>
                            ) : o.ok ? (
                              <span className="text-fog-50">{o.value_repr}</span>
                            ) : (
                              <span className="text-danger">
                                {o.error_type ?? o.value_repr}
                                {o.error_msg && <span className="block text-[12.5px] text-fog-400">{o.error_msg}</span>}
                              </span>
                            )}
                          </td>
                          {expected.size > 0 && (
                            <td className="px-4 py-2.5 text-center">
                              {match === undefined ? (
                                <span className="text-fog-500">–</span>
                              ) : match ? (
                                <IconCheck className="inline text-add" aria-label="matches" />
                              ) : (
                                <span className="inline-flex flex-col items-center">
                                  <IconX className="text-danger" aria-label="differs" />
                                  <span className="mono text-[11.5px] text-fog-500">want {exp}</span>
                                </span>
                              )}
                            </td>
                          )}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {impl.code ? (
            <section aria-labelledby="code-h">
              <div className="mb-2.5 flex items-center justify-between">
                <h3 id="code-h" className="eyebrow">
                  Generated code
                </h3>
                <CopyButton text={impl.code} />
              </div>
              <CodeBlock code={impl.code} label={`Code of implementation ${impl.index + 1}`} />
            </section>
          ) : (
            <p className="text-fog-400">Code not available yet.</p>
          )}
        </div>
      )}
    </Drawer>
  );
}
