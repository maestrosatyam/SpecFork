"""Programmatic API shared by the CLI, the MCP server, the HTTP server and the evaluation harness."""
from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

from . import sandbox
from .config import Settings
from .llm import ModelRouter
from .pipeline import SpecFork, new_run, render_tests
from .registry import Registry
from .types import Run


class ForkError(RuntimeError):
    pass


class Client:
    """High-level entry point. Holds settings, the model registry/router and the pipeline engine."""

    def __init__(self, settings: Settings | None = None, router: ModelRouter | None = None,
                 on_update: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.settings = settings or Settings.load()
        self.registry = router.registry if router is not None else Registry.load(self.settings.models_file)
        self.router = router or ModelRouter(self.registry, self.settings.api_keys,
                                            max_concurrency=self.settings.llm_concurrency,
                                            default_model=self.settings.fast_model)
        sandbox.configure(self.settings.sandbox_require_isolation, self.settings.sandbox_concurrency)
        self.engine = SpecFork(self.router, on_update or (lambda run: None), frame_thinking=self.settings.frame_thinking,
                               assumption_min_confidence=self.settings.assumption_min_confidence,
                               max_assumptions=self.settings.max_assumptions,
                               assumption_requires_witness=self.settings.assumption_requires_witness)

    async def __aenter__(self) -> Client:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.router.aclose()

    def new_run(self, spec: str, *, n_samples: int = 24, fast_model: str | None = None, deep_model: str | None = None,
                implementers: list[str] | None = None, assumptions: bool | None = None,
                signature: dict[str, Any] | None = None, exception_types: bool | None = None) -> dict[str, Any]:
        fast = self.registry.get(fast_model or self.settings.fast_model)
        deep = self.registry.get(deep_model or self.settings.deep_model)
        impl_keys = implementers or ([fast.key] if fast_model else self.settings.implementer_keys)
        run = new_run(secrets.token_urlsafe(12), spec, n_samples, None, fast.model, deep.model,
                      implementers=[self.registry.get(k).model for k in impl_keys],
                      assumptions=self.settings.assumptions if assumptions is None else assumptions,
                      exception_types=self.settings.exception_types if exception_types is None else exception_types,
                      adaptive_n=self.settings.adaptive_n, probe_rounds=self.settings.probe_rounds,
                      open_questions=self.settings.open_questions)
        if signature:
            run["signature"] = {**signature, "docstring": signature.get("docstring", "")}
        return run

    async def fork(self, spec: str, **kw: Any) -> Run:
        """Frame, fan out, execute, cluster and explain. Returns a run awaiting answers."""
        run = self.new_run(spec, **kw)
        await self.engine.run_all(run)
        if run["status"] == "error":
            raise ForkError(run.get("error") or "fork failed")
        return Run.model_validate(run)

    async def fork_raw(self, run: dict[str, Any]) -> dict[str, Any]:
        await self.engine.run_all(run)
        return run

    async def resolve(self, run: Run | dict[str, Any], answers: dict[str, str],
                      other: dict[str, str] | None = None) -> Run:
        """Apply answers (question id -> option id) and free-text answers (question id -> text)."""
        raw = run.model_dump() if isinstance(run, Run) else run
        await self.engine.resolve(raw, answers, other)
        return Run.model_validate(raw)

    async def converge(self, run: Run | dict[str, Any], n_samples: int | None = None) -> Run:
        """Re-fork the clarified spec and measure agreement with the locked tests."""
        raw = run.model_dump() if isinstance(run, Run) else run
        await self.engine.converge(raw, n_samples or raw["settings"]["n_samples"])
        return Run.model_validate(raw)

    @staticmethod
    def tests(run: Run | dict[str, Any], module: str = "solution") -> str:
        raw = run.model_dump() if isinstance(run, Run) else run
        res = raw.get("resolution")
        if not res:
            raise ForkError("resolve the run first")
        return render_tests(raw["signature"], res["locked_cases"], res["clarified_spec"], module=module)
