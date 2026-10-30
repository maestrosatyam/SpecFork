"""Model registry: capability profiles in data (``models.toml`` + user ``specfork.toml``), not in code."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BUILTIN = Path(__file__).with_name("models.toml")
APIS = {"openai_compat", "anthropic", "gemini"}
REASONING = {"chat_template_kwargs", "reasoning_effort", "anthropic_thinking", "gemini_thinking", "none"}


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class ModelProfile:
    key: str
    model: str
    api: str = "openai_compat"
    label: str = ""
    provider_label: str = ""
    base_url: str = ""
    key_env: str | None = None
    reasoning: str = "none"
    reasoning_extras: dict[str, dict[str, Any]] = field(default_factory=dict)
    seed: bool = False
    json_schema: bool = False
    price_per_m: tuple[float, float] | None = None
    max_concurrency: int = 16
    roles: tuple[str, ...] = ()

    @property
    def display(self) -> str:
        return self.label or self.model

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        if self.price_per_m is None:
            return None
        pin, pout = self.price_per_m
        return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000

    def public(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.display, "model": self.model, "provider_label": self.provider_label,
                "roles": list(self.roles), "priced": self.price_per_m is not None}


class Registry:
    def __init__(self, profiles: dict[str, ModelProfile]) -> None:
        self.profiles = profiles

    @classmethod
    def load(cls, extra_file: str | Path | None = None) -> Registry:
        raw: dict[str, dict[str, Any]] = {}
        files = [BUILTIN]
        if extra_file:
            files.append(Path(extra_file))
        elif Path("specfork.toml").exists():
            files.append(Path("specfork.toml"))
        for f in files:
            data = tomllib.loads(Path(f).read_text())
            for key, prof in (data.get("models") or {}).items():
                raw[key] = {**raw.get(key, {}), **prof}
        return cls({k: _profile(k, v) for k, v in raw.items()})

    def get(self, key_or_model: str) -> ModelProfile:
        if key_or_model in self.profiles:
            return self.profiles[key_or_model]
        for p in self.profiles.values():
            if p.model == key_or_model:
                return p
        raise RegistryError(f"unknown model profile '{key_or_model}' (known: {', '.join(sorted(self.profiles))})")

    def for_role(self, role: str) -> list[ModelProfile]:
        return [p for p in self.profiles.values() if role in p.roles]


def _profile(key: str, d: dict[str, Any]) -> ModelProfile:
    if not d.get("model"):
        raise RegistryError(f"profile '{key}': 'model' is required")
    api = d.get("api", "openai_compat")
    if api not in APIS:
        raise RegistryError(f"profile '{key}': api must be one of {sorted(APIS)}")
    reasoning = d.get("reasoning", "none")
    if reasoning not in REASONING:
        raise RegistryError(f"profile '{key}': reasoning must be one of {sorted(REASONING)}")
    price = d.get("price_per_m")
    if price is not None and (len(price) != 2 or any(not isinstance(x, (int, float)) or x < 0 for x in price)):
        raise RegistryError(f"profile '{key}': price_per_m must be [input, output] USD per 1M tokens")
    default_urls = {"anthropic": "https://api.anthropic.com", "gemini": "https://generativelanguage.googleapis.com"}
    return ModelProfile(
        key=key, model=str(d["model"]), api=api, label=str(d.get("label", "")),
        provider_label=str(d.get("provider_label", "")), base_url=str(d.get("base_url") or default_urls.get(api, "")),
        key_env=d.get("key_env"), reasoning=reasoning, reasoning_extras=dict(d.get("reasoning_extras") or {}),
        seed=bool(d.get("seed", False)), json_schema=bool(d.get("json_schema", False)),
        price_per_m=(float(price[0]), float(price[1])) if price is not None else None,
        max_concurrency=int(d.get("max_concurrency", 16)), roles=tuple(d.get("roles") or ()),
    )
