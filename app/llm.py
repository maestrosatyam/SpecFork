"""Nebius Token Factory client for NVIDIA Nemotron models.

Small, dependency-light async adapter over the OpenAI-compatible chat completions API with:
  * per-call telemetry (model, latency, tokens, estimated cost) recorded in a trace list
  * bounded concurrency, timeouts and retry with exponential backoff on 429/5xx
  * reasoning on/off via ``chat_template_kwargs.enable_thinking`` (Nemotron 3 / 3.5)
  * separation of the model's reasoning (``reasoning_content``) from its answer
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
MODEL_FAST = os.environ.get("MODEL_FAST", "nvidia/Nemotron-3_5-Lightning")
MODEL_DEEP = os.environ.get("MODEL_DEEP", "nvidia/Nemotron-3-Ultra-550b-a55b")

# USD per 1M tokens (input, output), from the Token Factory public catalog on 2026-10-29.
PRICES = {
    "nvidia/Nemotron-3_5-Lightning": (0.06, 0.24),
    "nvidia/Nemotron-3-Ultra-550b-a55b": (1.00, 3.00),
    "nvidia/Nemotron-3.5-Super-VL": (0.30, 0.90),
}

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.S)


class LLMError(RuntimeError):
    pass


@dataclass
class CallRecord:
    purpose: str
    model: str
    thinking: bool
    latency_s: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    ok: bool = True
    error: str | None = None
    request_id: str | None = None
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Completion:
    content: str
    reasoning: str
    record: CallRecord
    tool_calls: list[dict[str, Any]] | None = None


def split_reasoning(message: dict[str, Any]) -> tuple[str, str]:
    """Return (answer, reasoning) from a chat message, handling both the
    ``reasoning_content`` field and inline ``<think>...</think>`` blocks."""
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
    inline = _THINK_RE.findall(content)
    if inline:
        reasoning = (reasoning + "\n" + "\n".join(inline)).strip()
        content = _THINK_RE.sub("", content)
    if "</think>" in content:  # opening tag consumed by the chat template
        head, _, tail = content.partition("</think>")
        reasoning = (reasoning + "\n" + head).strip()
        content = tail
    return content.strip(), reasoning.strip()


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000


class NebiusClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        max_concurrency: int = 16,
        timeout_s: float = 120.0,
        max_retries: int = 4,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = os.environ.get("NEBIUS_API_KEY", "") if api_key is None else api_key
        self.base_url = base_url.rstrip("/")
        self.sem = asyncio.Semaphore(max_concurrency)
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_s,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str = MODEL_FAST,
        purpose: str = "chat",
        thinking: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        seed: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        response_format: dict[str, Any] | None = None,
        trace: list[CallRecord] | None = None,
        template_kwargs: dict[str, Any] | None = None,
    ) -> Completion:
        if not self.configured:
            raise LLMError("NEBIUS_API_KEY is not configured")
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": thinking, **(template_kwargs or {})},
        }
        if seed is not None:
            body["seed"] = seed
        if tools:
            body["tools"] = tools
            if tool_choice is not None:
                body["tool_choice"] = tool_choice
        if response_format:
            body["response_format"] = response_format

        last_err = "unknown error"
        async with self.sem:
            for attempt in range(self.max_retries + 1):
                t0 = time.perf_counter()
                try:
                    r = await self._http().post(f"{self.base_url}/chat/completions", json=body)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_err = f"transport: {type(e).__name__}"
                    await self._backoff(attempt)
                    continue
                latency = time.perf_counter() - t0
                if r.status_code == 429 or r.status_code >= 500:
                    last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                    await self._backoff(attempt, r.headers.get("retry-after"))
                    continue
                if r.status_code != 200:
                    rec = CallRecord(purpose, model, thinking, latency, ok=False, error=f"HTTP {r.status_code}: {r.text[:300]}")
                    if trace is not None:
                        trace.append(rec)
                    raise LLMError(rec.error or "")
                data = r.json()
                msg = data["choices"][0]["message"]
                content, reasoning = split_reasoning(msg)
                usage = data.get("usage") or {}
                pt, ct = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
                rec = CallRecord(
                    purpose, model, thinking, round(latency, 3), pt, ct,
                    round(estimate_cost(model, pt, ct), 7), request_id=data.get("id"),
                )
                if trace is not None:
                    trace.append(rec)
                return Completion(content, reasoning, rec, msg.get("tool_calls"))
        rec = CallRecord(purpose, model, thinking, 0.0, ok=False, error=last_err)
        if trace is not None:
            trace.append(rec)
        raise LLMError(f"exhausted retries: {last_err}")

    async def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        if attempt >= self.max_retries:
            return
        delay = min(20.0, 0.75 * (2**attempt)) + random.random() * 0.3
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        await asyncio.sleep(delay)


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array found in a model reply (tolerates code fences / prose)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        while start != -1:
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(text)):
                ch = text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == open_c:
                    depth += 1
                elif ch == close_c:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break
            start = text.find(open_c, start + 1)
    raise ValueError("no JSON found in model output")
