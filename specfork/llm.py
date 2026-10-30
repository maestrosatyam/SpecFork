"""Provider-neutral model calls.

``ModelRouter.chat`` takes generic intents (reasoning on/off with an effort level, JSON output, seed) and a
model profile key; each adapter translates them into its own wire format:

* ``openai_compat``: OpenAI-style ``/chat/completions`` (Nebius Token Factory, NVIDIA NIM, vLLM, SGLang,
  OpenAI, OpenRouter, Together, Groq, Fireworks, Ollama, LM Studio). Reasoning is switched with
  ``chat_template_kwargs`` (Nemotron, Qwen) or ``reasoning_effort`` (OpenAI-style), as the profile says.
* ``anthropic``: Messages API with extended thinking.
* ``gemini``: ``generateContent`` with a thinking budget.

Every call is recorded (model, latency, tokens, cost from the profile price, reasoning excerpt), retried with
exponential backoff on 429/5xx/transport errors, and bounded by a concurrency semaphore.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from .registry import ModelProfile, Registry, RegistryError

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.S)
EFFORT_BUDGET = {"low": 2048, "medium": 8192, "high": 16384}


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
    priced: bool = True

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


def estimate_cost(profile: ModelProfile, prompt_tokens: int, completion_tokens: int) -> float:
    c = profile.cost(prompt_tokens, completion_tokens)
    return 0.0 if c is None else c


class ModelRouter:
    """Dispatches chat requests to the adapter named by each model profile."""

    def __init__(self, registry: Registry, api_keys: dict[str, str] | None = None, *, max_concurrency: int = 16,
                 timeout_s: float = 120.0, max_retries: int = 4, transport: httpx.AsyncBaseTransport | None = None,
                 default_model: str = "lightning") -> None:
        self.registry = registry
        self.api_keys = dict(api_keys or {})
        self.sem = asyncio.Semaphore(max_concurrency)
        self._profile_sems: dict[str, asyncio.Semaphore] = {}
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.default_model = default_model
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def profile(self, model: str) -> ModelProfile:
        return self.registry.get(model)

    def configured(self, model: str | None = None) -> bool:
        try:
            p = self.profile(model or self.default_model)
        except RegistryError:
            return False
        return not p.key_env or bool(self.api_keys.get(p.key_env))

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s, transport=self._transport)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        purpose: str = "chat",
        thinking: bool = False,
        effort: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        seed: int | None = None,
        json_mode: bool = False,
        trace: list[CallRecord] | None = None,
    ) -> Completion:
        try:
            p = self.profile(model or self.default_model)
        except RegistryError as e:
            raise LLMError(str(e)) from e
        key = self.api_keys.get(p.key_env, "") if p.key_env else ""
        if p.key_env and not key:
            raise LLMError(f"{p.key_env} is not configured (needed by model profile '{p.key}')")
        build, parse = ADAPTERS[p.api]
        url, headers, body = build(p, key, messages, thinking=thinking, effort=effort, temperature=temperature,
                                   max_tokens=max_tokens, seed=seed, json_mode=json_mode)
        last_err = "unknown error"
        psem = self._profile_sems.setdefault(p.key, asyncio.Semaphore(max(1, p.max_concurrency)))
        async with self.sem, psem:
            for attempt in range(self.max_retries + 1):
                t0 = time.perf_counter()
                try:
                    r = await self._http().post(url, json=body, headers=headers)
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
                    rec = CallRecord(purpose, p.model, thinking, latency, ok=False, error=f"HTTP {r.status_code}: {r.text[:300]}")
                    if trace is not None:
                        trace.append(rec)
                    raise LLMError(rec.error or "")
                content, reasoning, pt, ct, rid, tool_calls = parse(r.json())
                cost = p.cost(pt, ct)
                rec = CallRecord(purpose, p.model, thinking, round(latency, 3), pt, ct, round(cost or 0.0, 7),
                                 request_id=rid, priced=cost is not None)
                if trace is not None:
                    trace.append(rec)
                return Completion(content, reasoning, rec, tool_calls)
        rec = CallRecord(purpose, p.model, thinking, 0.0, ok=False, error=last_err)
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


# ---------------------------------------------------------------- adapters

def _openai_build(p: ModelProfile, key: str, messages: list[dict[str, Any]], *, thinking: bool, effort: str | None,
                  temperature: float, max_tokens: int, seed: int | None, json_mode: bool):
    body: dict[str, Any] = {"model": p.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if seed is not None and p.seed:
        body["seed"] = seed
    if json_mode and p.json_schema:
        body["response_format"] = {"type": "json_object"}
    if p.reasoning == "chat_template_kwargs":
        extras = p.reasoning_extras.get(effort or "", {}) if thinking else {}
        body["chat_template_kwargs"] = {"enable_thinking": thinking, **extras}
    elif p.reasoning == "reasoning_effort" and thinking:
        body["reasoning_effort"] = effort or "medium"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return f"{p.base_url.rstrip('/')}/chat/completions", headers, body


def _openai_parse(data: dict[str, Any]):
    msg = data["choices"][0]["message"]
    content, reasoning = split_reasoning(msg)
    usage = data.get("usage") or {}
    return (content, reasoning, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0),
            data.get("id"), msg.get("tool_calls"))


def _anthropic_build(p: ModelProfile, key: str, messages: list[dict[str, Any]], *, thinking: bool, effort: str | None,
                     temperature: float, max_tokens: int, seed: int | None, json_mode: bool):
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    if json_mode:
        system = (system + "\n\nReply with JSON only.").strip()
    body: dict[str, Any] = {"model": p.model, "max_tokens": max_tokens,
                            "messages": [m for m in messages if m["role"] != "system"]}
    if system:
        body["system"] = system
    if thinking and p.reasoning == "anthropic_thinking":
        budget = EFFORT_BUDGET.get(effort or "medium", 8192)
        body["thinking"] = {"type": "enabled", "budget_tokens": budget}
        body["max_tokens"] = max(max_tokens, budget + 1024)
    else:
        body["temperature"] = min(temperature, 1.0)
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return f"{p.base_url.rstrip('/')}/v1/messages", headers, body


def _anthropic_parse(data: dict[str, Any]):
    blocks = data.get("content") or []
    content = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    reasoning = "".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking")
    usage = data.get("usage") or {}
    return (content.strip(), reasoning.strip(), int(usage.get("input_tokens") or 0),
            int(usage.get("output_tokens") or 0), data.get("id"), None)


def _gemini_build(p: ModelProfile, key: str, messages: list[dict[str, Any]], *, thinking: bool, effort: str | None,
                  temperature: float, max_tokens: int, seed: int | None, json_mode: bool):
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] != "system"]
    gen: dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if seed is not None and p.seed:
        gen["seed"] = seed
    if json_mode and p.json_schema:
        gen["responseMimeType"] = "application/json"
    if p.reasoning == "gemini_thinking":
        gen["thinkingConfig"] = ({"thinkingBudget": EFFORT_BUDGET.get(effort or "medium", 8192), "includeThoughts": True}
                                 if thinking else {"thinkingBudget": 0})
    body: dict[str, Any] = {"contents": contents, "generationConfig": gen}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    headers = {"x-goog-api-key": key}
    return f"{p.base_url.rstrip('/')}/v1beta/models/{p.model}:generateContent", headers, body


def _gemini_parse(data: dict[str, Any]):
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    content = "".join(x.get("text", "") for x in parts if not x.get("thought"))
    reasoning = "".join(x.get("text", "") for x in parts if x.get("thought"))
    u = data.get("usageMetadata") or {}
    ct = int(u.get("candidatesTokenCount") or 0) + int(u.get("thoughtsTokenCount") or 0)
    return content.strip(), reasoning.strip(), int(u.get("promptTokenCount") or 0), ct, data.get("responseId"), None


ADAPTERS = {
    "openai_compat": (_openai_build, _openai_parse),
    "anthropic": (_anthropic_build, _anthropic_parse),
    "gemini": (_gemini_build, _gemini_parse),
}


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array found in a model reply (tolerates code fences / prose)."""
    text = text.strip()[:200_000]  # bound the work done on model output
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        first, last = text.find(open_c), text.rfind(close_c)
        if first != -1 and last > first:  # common case: one object surrounded by prose
            try:
                return json.loads(text[first : last + 1])
            except json.JSONDecodeError:
                pass
        start = text.find(open_c)
        attempts = 0
        while start != -1 and attempts < 8:  # bounded: hostile output cannot make this quadratic
            attempts += 1
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
