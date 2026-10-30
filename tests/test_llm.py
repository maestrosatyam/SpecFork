import json

import httpx
import pytest

from app.llm import LLMError, NebiusClient, estimate_cost, extract_json, split_reasoning


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
    assert estimate_cost("nvidia/Nemotron-3_5-Lightning", 1_000_000, 1_000_000) == pytest.approx(0.30)


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

    c = NebiusClient(api_key="k", transport=httpx.MockTransport(handler), max_retries=2)
    trace = []
    out = await c.chat([{"role": "user", "content": "x"}], trace=trace)
    assert out.content == "hi" and calls["n"] == 2
    assert trace[0].prompt_tokens == 10 and trace[0].ok
    await c.aclose()


@pytest.mark.asyncio
async def test_client_error_raises_and_records():
    c = NebiusClient(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad")))
    trace = []
    with pytest.raises(LLMError):
        await c.chat([{"role": "user", "content": "x"}], trace=trace)
    assert trace and not trace[0].ok
    await c.aclose()


@pytest.mark.asyncio
async def test_unconfigured():
    with pytest.raises(LLMError):
        await NebiusClient(api_key="").chat([])


def test_extract_json_is_bounded_on_hostile_output():
    import time
    hostile = "{" * 40000
    t0 = time.perf_counter()
    with pytest.raises(ValueError):
        extract_json(hostile)
    assert time.perf_counter() - t0 < 2.0
