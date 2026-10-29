"""Behavioural clustering of implementations and selection of witness inputs.

Pure functions, no I/O, fully deterministic — the "code decides" part of SpecFork.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def outcome_key(o: dict[str, Any] | None) -> str:
    """Comparable behaviour token for one outcome. All exceptions compare equal ("raises")."""
    if o is None:
        return "missing"
    return o["value_repr"] if o.get("ok") else "raises"


@dataclass
class ClusterResult:
    clusters: list[dict[str, Any]]
    impl_cluster: dict[str, str]


def cluster_impls(outcomes: dict[str, dict[str, dict[str, Any]]], input_ids: list[str]) -> ClusterResult:
    """Group implementations whose outcome on every input is identical.

    ``outcomes``: impl_id -> input_id -> Outcome. Clusters are ordered by size desc then first impl id.
    """
    groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for impl_id, per_input in outcomes.items():
        sig = tuple(outcome_key(per_input.get(i)) for i in input_ids)
        groups[sig].append(impl_id)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), _impl_order(kv[1][0])))
    total = sum(len(v) for v in groups.values()) or 1
    clusters, impl_cluster = [], {}
    for idx, (sig, impls) in enumerate(ordered):
        cid = f"c{idx}"
        raises = sum(1 for k in sig if k == "raises")
        kind = "crash" if input_ids and raises / len(input_ids) >= 0.6 else "behavior"
        clusters.append({
            "id": cid, "label": LABELS[idx] if idx < len(LABELS) else f"Z{idx}",
            "impl_ids": sorted(impls, key=_impl_order), "size": len(impls), "share": round(len(impls) / total, 4),
            "representative_impl_id": sorted(impls, key=_impl_order)[0], "kind": kind,
        })
        for i in impls:
            impl_cluster[i] = cid
    return ClusterResult(clusters, impl_cluster)


def _impl_order(impl_id: str) -> tuple[int, str]:
    digits = "".join(ch for ch in impl_id if ch.isdigit())
    return (int(digits) if digits else 0, impl_id)


@dataclass
class Axis:
    """One way the implementations split: a partition of clusters, witnessed by one or more inputs."""

    partition: tuple[tuple[str, ...], ...]          # groups of cluster ids, sorted
    witness_input_ids: list[str] = field(default_factory=list)
    group_values: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # input -> [(group_key, value)]
    weight: float = 0.0                              # minority mass (impl count outside the biggest group)


def find_axes(
    clusters: list[dict[str, Any]],
    rep_outcomes: dict[str, dict[str, dict[str, Any]]],
    input_ids: list[str],
    max_axes: int = 6,
    max_witnesses_per_axis: int = 3,
) -> list[Axis]:
    """Find inputs on which clusters disagree, grouped by the cluster partition they induce.

    ``rep_outcomes``: cluster_id -> input_id -> Outcome of the cluster's representative.
    Crash clusters are ignored for axis discovery (they are reported as likely bugs).
    Returns axes sorted by weight (number of implementations not in the largest group), strongest first.
    """
    live = [c for c in clusters if c["kind"] != "crash"]
    if len(live) < 2:
        return []
    size = {c["id"]: c["size"] for c in live}
    axes: dict[tuple[tuple[str, ...], ...], Axis] = {}
    for inp in input_ids:
        by_val: dict[str, list[str]] = defaultdict(list)
        for c in live:
            by_val[outcome_key(rep_outcomes[c["id"]].get(inp))].append(c["id"])
        if len(by_val) < 2:
            continue
        partition = tuple(sorted(tuple(sorted(g)) for g in by_val.values()))
        ax = axes.get(partition)
        if ax is None:
            masses = sorted((sum(size[cid] for cid in g) for g in partition), reverse=True)
            ax = Axis(partition=partition, weight=float(sum(masses[1:])))
            axes[partition] = ax
        if len(ax.witness_input_ids) < max_witnesses_per_axis:
            ax.witness_input_ids.append(inp)
            ax.group_values[inp] = [(",".join(sorted(g)), v) for v, g in by_val.items()]
    ranked = sorted(axes.values(), key=lambda a: (-a.weight, len(a.partition), a.witness_input_ids[0]))
    # Keep axes that add new distinctions: greedy cover of cluster pairs.
    chosen: list[Axis] = []
    separated: set[frozenset[str]] = set()
    for ax in ranked:
        pairs = _separated_pairs(ax.partition)
        if pairs - separated:
            chosen.append(ax)
            separated |= pairs
        if len(chosen) >= max_axes:
            break
    return chosen


def _separated_pairs(partition: tuple[tuple[str, ...], ...]) -> set[frozenset[str]]:
    out = set()
    for i, g1 in enumerate(partition):
        for g2 in partition[i + 1 :]:
            for a in g1:
                for b in g2:
                    out.add(frozenset((a, b)))
    return out


def surviving_clusters(
    clusters: list[dict[str, Any]], chosen_cluster_sets: list[set[str]]
) -> tuple[list[str], bool]:
    """Intersect the cluster sets of the chosen answers. If the answers are jointly unsatisfiable,
    fall back to the clusters satisfying the most answers. Returns (cluster ids, exact)."""
    ids = [c["id"] for c in clusters if c["kind"] != "crash"] or [c["id"] for c in clusters]
    alive = set(ids)
    for s in chosen_cluster_sets:
        alive &= s
    if alive:
        return [c for c in ids if c in alive], True
    score = Counter({c: sum(1 for s in chosen_cluster_sets if c in s) for c in ids})
    best = max(score.values()) if score else 0
    return [c for c in ids if score[c] == best], False


def agreement(outcomes: dict[str, dict[str, dict[str, Any]]], expected: dict[str, str]) -> tuple[int, int]:
    """Count implementations whose behaviour matches ``expected`` (input_id -> outcome key) on every case."""
    n = passed = 0
    for per_input in outcomes.values():
        n += 1
        if all(outcome_key(per_input.get(i)) == k for i, k in expected.items()):
            passed += 1
    return passed, n
