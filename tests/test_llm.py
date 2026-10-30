import json

import httpx
import pytest

from specfork.llm import LLMError, estimate_cost, extract_json, split_reasoning
from specfork.registry import Registry, RegistryError
from tests.fake_llm import make_router


def test_split_reasoning_field():
    a, r = split_reasoning({"content": "42", "reasoning_content": "think hard"})
    assert (a, r) == ("42", "think hard")


def test_split_reasoning_inline_and_dangling():
    assert split_reasoning({"content": "<think>x</think> 42"}) == ("42", "x")
    assert split_reasoning({"content": "plan stuff</think>\n42"}) == ("42", "plan stuff")


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! here: {"a": {"b": "}"}} trailing') == {"a": {"b": "}"}}
    assert extract_json("[1, 2]") == [1, 2]
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_cost():
    assert estimate_cost(Registry.load().get("lightning"), 1_000_000, 1_000_000) == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_retry_then_success_and_trace():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content)
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert request.headers["authorization"] == "Bearer k"
        if calls["n"] == 1:
            return httpx.Response(429, text="slow down", headers={"retry-after": "0"})
        return httpx.Response(200, json={
            "id": "r1", "choices": [{"message": {"content": "hi", "reasoning_content": None}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })

    c = make_router(httpx.MockTransport(handler), key="k", max_retries=2)
    trace = []
    out = await c.chat([{"role": "user", "content": "x"}], trace=trace)
    assert out.content == "hi" and calls["n"] == 2
    assert trace[0].prompt_tokens == 10 and trace[0].ok
    await c.aclose()


@pytest.mark.asyncio
async def test_client_error_raises_and_records():
    c = make_router(httpx.MockTransport(lambda r: httpx.Response(400, text="bad")), key="k")
    trace = []
    with pytest.raises(LLMError):
        await c.chat([{"role": "user", "content": "x"}], trace=trace)
    assert trace and not trace[0].ok
    await c.aclose()


@pytest.mark.asyncio
async def test_unconfigured():
    with pytest.raises(LLMError):
        await make_router(key="").chat([])


def test_extract_json_is_bounded_on_hostile_output():
    import time
    hostile = "{" * 40000
    t0 = time.perf_counter()
    with pytest.raises(ValueError):
        extract_json(hostile)
    assert time.perf_counter() - t0 < 2.0


# ---- provider registry and adapters (no network)

from specfork.llm import ModelRouter  # noqa: E402


def _registry(tmp_path, body: str) -> Registry:
    f = tmp_path / "specfork.toml"
    f.write_text(body)
    return Registry.load(f)


def _capture(store: dict, response: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        store["url"] = str(request.url)
        store["headers"] = dict(request.headers)
        store["body"] = json.loads(request.content)
        return httpx.Response(200, json=response)
    return httpx.MockTransport(handler)


OPENAI_OK = {"id": "x", "choices": [{"message": {"content": "{\"a\": 1}"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


async def test_plain_openai_profile_never_sends_chat_template_kwargs(tmp_path):
    reg = _registry(tmp_path, '[models.local]\nmodel = "qwen2.5-coder"\nbase_url = "http://localhost:11434/v1"\nreasoning = "none"\nprice_per_m = [0, 0]\n')
    seen: dict = {}
    r = ModelRouter(reg, {}, transport=_capture(seen, OPENAI_OK))
    await r.chat([{"role": "user", "content": "x"}], model="local", thinking=True, effort="medium", seed=3)
    assert "chat_template_kwargs" not in seen["body"] and "seed" not in seen["body"]
    assert seen["url"] == "http://localhost:11434/v1/chat/completions" and "authorization" not in seen["headers"]
    await r.aclose()


async def test_reasoning_effort_profile(tmp_path):
    reg = _registry(tmp_path, '[models.o]\nmodel = "o-mini"\nbase_url = "https://api.example/v1"\nkey_env = "EX_API_KEY"\nreasoning = "reasoning_effort"\nseed = true\njson_schema = true\n')
    seen: dict = {}
    r = ModelRouter(reg, {"EX_API_KEY": "k"}, transport=_capture(seen, OPENAI_OK))
    res = await r.chat([{"role": "user", "content": "x"}], model="o", thinking=True, effort="high", seed=1, json_mode=True)
    assert seen["body"]["reasoning_effort"] == "high" and seen["body"]["seed"] == 1
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert res.record.priced is False and res.record.cost_usd == 0.0  # unpriced profile is flagged
    await r.aclose()


async def test_nemotron_profile_sends_template_kwargs_with_effort_extras():
    seen: dict = {}
    r = make_router(_capture(seen, OPENAI_OK))
    await r.chat([{"role": "user", "content": "x"}], model="ultra", thinking=True, effort="medium")
    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": True, "medium_effort": True}
    await r.chat([{"role": "user", "content": "x"}], model="lightning", thinking=False)
    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    await r.aclose()


async def test_anthropic_adapter(tmp_path):
    reg = _registry(tmp_path, '[models.c]\napi = "anthropic"\nmodel = "claude-x"\nkey_env = "ANTHROPIC_API_KEY"\nreasoning = "anthropic_thinking"\nprice_per_m = [1, 5]\n')
    seen: dict = {}
    resp = {"id": "m1", "content": [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "391"}],
            "usage": {"input_tokens": 10, "output_tokens": 20}}
    r = ModelRouter(reg, {"ANTHROPIC_API_KEY": "k"}, transport=_capture(seen, resp))
    out = await r.chat([{"role": "system", "content": "S"}, {"role": "user", "content": "q"}], model="c", thinking=True, effort="low", max_tokens=500)
    assert seen["url"].endswith("/v1/messages") and seen["headers"]["x-api-key"] == "k"
    assert seen["body"]["system"] == "S" and seen["body"]["thinking"]["budget_tokens"] == 2048
    assert seen["body"]["max_tokens"] > 2048 and "temperature" not in seen["body"]
    assert (out.content, out.reasoning, out.record.prompt_tokens) == ("391", "hmm", 10)
    assert out.record.cost_usd == pytest.approx((10 * 1 + 20 * 5) / 1e6)
    await r.aclose()


async def test_gemini_adapter(tmp_path):
    reg = _registry(tmp_path, '[models.g]\napi = "gemini"\nmodel = "gemini-x"\nkey_env = "GEMINI_API_KEY"\nreasoning = "gemini_thinking"\njson_schema = true\n')
    seen: dict = {}
    resp = {"responseId": "g1", "candidates": [{"content": {"parts": [{"text": "think", "thought": True}, {"text": "{}"}]}}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4, "thoughtsTokenCount": 5}}
    r = ModelRouter(reg, {"GEMINI_API_KEY": "k"}, transport=_capture(seen, resp))
    out = await r.chat([{"role": "system", "content": "S"}, {"role": "user", "content": "q"}], model="g", thinking=False, json_mode=True)
    assert seen["url"].endswith("/v1beta/models/gemini-x:generateContent") and seen["headers"]["x-goog-api-key"] == "k"
    assert seen["body"]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert (out.content, out.reasoning, out.record.completion_tokens) == ("{}", "think", 9)
    await r.aclose()


def test_registry_validation(tmp_path):
    with pytest.raises(RegistryError):
        _registry(tmp_path, '[models.bad]\nmodel = "x"\napi = "nope"\n')
    with pytest.raises(RegistryError):
        _registry(tmp_path, '[models.bad]\nmodel = "x"\nprice_per_m = [1]\n')
    reg = Registry.load()
    assert reg.get("nvidia/Nemotron-3-Ultra-550b-a55b").key == "ultra"
    with pytest.raises(RegistryError):
        reg.get("does-not-exist")
