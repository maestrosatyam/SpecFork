"""All runtime configuration in one place.

Nothing in the ``specfork`` package reads ``os.environ`` at import time. Build a :class:`Settings` once
(``Settings.load()`` reads the environment and an optional ``.env`` file) and pass it explicitly.

| Variable | Default | Meaning |
|---|---|---|
| ``SPECFORK_FAST_MODEL`` | ``lightning`` | profile key for framing, fan-out and re-fork |
| ``SPECFORK_DEEP_MODEL`` | ``ultra`` | profile key for explanations, assumptions and the clarified spec |
| ``SPECFORK_IMPLEMENTERS`` | (fast model) | comma-separated profile keys for a mixed-model fan-out |
| ``SPECFORK_MODELS_FILE`` | ``./specfork.toml`` if present | extra model profiles |
| ``SPECFORK_PUBLIC_DEMO`` | ``0`` | public-demo hardening (no OpenAPI, priced models only, memory-only store) |
| ``SPECFORK_ASSUMPTIONS`` | ``1`` | look for silent assumptions by default |
| ``SPECFORK_ASSUMPTION_MIN_CONFIDENCE`` / ``SPECFORK_MAX_ASSUMPTIONS`` | 0.6 / 2 | strictness of the assumption review |
| ``SPECFORK_DB`` | ``specfork.db`` (``""`` = memory only) | SQLite file for runs (ignored in public-demo mode) |
| ``RATE_LIMIT_RUNS`` / ``RATE_LIMIT_WINDOW_S`` / ``DAILY_BUDGET_USD`` | 6 / 600 / 5 | abuse and cost controls |
| ``LLM_CONCURRENCY`` | 16 | concurrent model calls |
| ``SANDBOX_REQUIRE_ISOLATION`` | ``0`` | refuse to run model code without a network namespace |
| ``SANDBOX_CONCURRENCY`` | auto | concurrent sandbox processes |
| ``FRAME_THINKING`` | ``0`` | reasoning on for the framing call |
| ``MAX_SSE`` | 40 | concurrent event streams |
| ``<KEY_ENV>`` of each profile, e.g. ``NEBIUS_API_KEY`` | – | API keys (variable names must end in ``_KEY`` or ``_TOKEN``) |
| ``SPECFORK_ALLOW_WEAK_SANDBOX`` | ``0`` | MCP server only: allow running without network isolation |
| ``WEB_DIST`` | auto | directory of the built web UI |

Legacy names ``MODEL_FAST`` / ``MODEL_DEEP`` (profile keys or model ids) are still accepted.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    fast_model: str = Field(default="lightning", validation_alias="SPECFORK_FAST_MODEL")
    deep_model: str = Field(default="ultra", validation_alias="SPECFORK_DEEP_MODEL")
    implementers: str = Field(default="", validation_alias="SPECFORK_IMPLEMENTERS")
    models_file: str | None = Field(default=None, validation_alias="SPECFORK_MODELS_FILE")
    public_demo: bool = Field(default=False, validation_alias="SPECFORK_PUBLIC_DEMO")
    assumptions: bool = Field(default=True, validation_alias="SPECFORK_ASSUMPTIONS")
    assumption_min_confidence: float = Field(default=0.6, ge=0, le=1, validation_alias="SPECFORK_ASSUMPTION_MIN_CONFIDENCE")
    max_assumptions: int = Field(default=2, ge=0, le=5, validation_alias="SPECFORK_MAX_ASSUMPTIONS")
    db_path: str = Field(default="specfork.db", validation_alias="SPECFORK_DB")
    rate_limit_runs: int = Field(default=6, validation_alias="RATE_LIMIT_RUNS")
    rate_limit_window_s: float = Field(default=600.0, validation_alias="RATE_LIMIT_WINDOW_S")
    daily_budget_usd: float = Field(default=5.0, validation_alias="DAILY_BUDGET_USD")
    llm_concurrency: int = Field(default=16, validation_alias="LLM_CONCURRENCY")
    sandbox_require_isolation: bool = Field(default=False, validation_alias="SANDBOX_REQUIRE_ISOLATION")
    sandbox_concurrency: int = Field(default=0, validation_alias="SANDBOX_CONCURRENCY")
    frame_thinking: bool = Field(default=False, validation_alias="FRAME_THINKING")
    max_sse: int = Field(default=40, validation_alias="MAX_SSE")
    # API keys by environment-variable name (filled by ``load`` for every key_env the registry mentions)
    api_keys: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)

    @property
    def implementer_keys(self) -> list[str]:
        keys = [k.strip() for k in self.implementers.split(",") if k.strip()]
        return keys or [self.fast_model]

    @classmethod
    def load(cls, env_file: str | os.PathLike[str] | None = ".env", **overrides: Any) -> Settings:
        """Read settings from the environment (and ``env_file`` if it exists). Never mutates os.environ."""
        env: dict[str, str] = {}
        if env_file and Path(env_file).exists():
            env.update(parse_env_file(Path(env_file)))
        env.update(os.environ)
        # legacy aliases
        if "MODEL_FAST" in env and "SPECFORK_FAST_MODEL" not in env:
            env["SPECFORK_FAST_MODEL"] = env["MODEL_FAST"]
        if "MODEL_DEEP" in env and "SPECFORK_DEEP_MODEL" not in env:
            env["SPECFORK_DEEP_MODEL"] = env["MODEL_DEEP"]
        known = {f.validation_alias for f in cls.model_fields.values() if isinstance(f.validation_alias, str)}
        data: dict[str, Any] = {k: v for k, v in env.items() if k in known}
        s = cls.model_validate({**data, **{_alias(cls, k): v for k, v in overrides.items()}})
        s.api_keys = {k: v for k, v in env.items() if k.endswith(("_KEY", "_TOKEN"))}
        return s


def _alias(cls: type[Settings], name: str) -> str:
    f = cls.model_fields.get(name)
    return f.validation_alias if f is not None and isinstance(f.validation_alias, str) else name


def parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out
