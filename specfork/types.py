"""Typed views of a SpecFork run (Pydantic). Unknown fields are kept, so records stay forward-compatible."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class Param(_Model):
    name: str
    type: str
    description: str = ""


class Signature(_Model):
    name: str
    params: list[Param]
    returns: dict[str, str]


class ProbeInput(_Model):
    id: str
    args: dict[str, Any]
    source: str = "model"
    note: str = ""


class Outcome(_Model):
    ok: bool
    value_repr: str
    error_type: str | None = None
    error_msg: str | None = None


class Implementation(_Model):
    id: str
    index: int
    model: str
    status: str
    code: str | None = None
    reject_reason: str | None = None
    cluster_id: str | None = None
    outcomes: dict[str, Outcome] | None = None


class Cluster(_Model):
    id: str
    label: str
    impl_ids: list[str]
    size: int
    share: float
    representative_impl_id: str
    kind: Literal["behavior", "crash"]
    summary: str | None = None


class Example(_Model):
    input_id: str
    value_repr: str


class Option(_Model):
    id: str
    label: str
    cluster_ids: list[str] = []
    examples: list[Example] = []
    impl_count: int = 0
    is_alternative: bool = False
    is_custom: bool = False
    is_bug: bool = False
    note: str | None = None


class Question(_Model):
    id: str
    kind: Literal["ambiguity", "likely_bug", "assumption"]
    text: str
    why: str = ""
    witness_input_ids: list[str] = []
    options: list[Option]
    answer_option_id: str | None = None


class LockedCase(_Model):
    input_id: str
    args: dict[str, Any]
    expected_repr: str
    basis: str = "decided"


class Convergence(_Model):
    n: int
    passed: int = 0
    executed: int | None = None
    agreement_after: float = 0.0
    clusters_after: int = 0
    status: str


class Resolution(_Model):
    answers: dict[str, str | None]
    clarified_spec: str
    decisions: list[str]
    tests_code: str
    reference_code: str | None = None
    locked_cases: list[LockedCase]
    agreement_before: float
    open_input_ids: list[str] = []
    unlocked_input_ids: list[str] = []
    custom_impl_id: str | None = None
    convergence: Convergence | None = None


class Metrics(_Model):
    total_cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    n_calls: int
    wall_time_s: float


class Run(_Model):
    id: str
    status: Literal["running", "awaiting_answers", "resolving", "resolved", "converging", "error"]
    stage: str
    spec: str
    settings: dict[str, Any]
    signature: Signature | None = None
    inputs: list[ProbeInput] = []
    implementations: list[Implementation] = []
    clusters: list[Cluster] = []
    questions: list[Question] = []
    resolution: Resolution | None = None
    trace: list[dict[str, Any]] = []
    metrics: Metrics
    error: str | None = None

    @property
    def open_questions(self) -> list[Question]:
        """Questions the owner must answer (ambiguities and silent assumptions)."""
        return [q for q in self.questions if q.kind in ("ambiguity", "assumption")]

    @property
    def behaviours(self) -> list[Cluster]:
        return [c for c in self.clusters if c.kind == "behavior"]
