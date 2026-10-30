#!/usr/bin/env python3
"""Eligibility probe: real NVIDIA Nemotron inference through Nebius Token Factory.

Runs a set of small live requests against the Token Factory OpenAI-compatible API
and writes a sanitized evidence file (no secrets) to docs/results/nebius_model_runtime_probe.json.

Usage:  NEBIUS_API_KEY=... python scripts/probe_nebius.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
MODELS = {
    "fast": os.environ.get("MODEL_FAST", "nvidia/Nemotron-3_5-Lightning"),
    "deep": os.environ.get("MODEL_DEEP", "nvidia/Nemotron-3-Ultra-550b-a55b"),
}


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def call(client: httpx.Client, name: str, body: dict) -> dict:
    t0 = time.perf_counter()
    try:
        r = client.post(f"{BASE_URL}/chat/completions", json=body, timeout=180)
        latency = time.perf_counter() - t0
        rec = {"case": name, "model": body["model"], "http_status": r.status_code, "latency_s": round(latency, 3)}
        if r.status_code != 200:
            rec["error"] = r.text[:600]
            return rec
        data = r.json()
        msg = data["choices"][0]["message"]
        rec.update(
            {
                "response_id": data.get("id"),
                "response_model": data.get("model"),
                "finish_reason": data["choices"][0].get("finish_reason"),
                "usage": data.get("usage"),
                "content": (msg.get("content") or "")[:800],
                "has_reasoning_content": bool(msg.get("reasoning_content") or msg.get("reasoning")),
                "reasoning_excerpt": ((msg.get("reasoning_content") or msg.get("reasoning") or "")[:400]),
                "tool_calls": msg.get("tool_calls"),
            }
        )
        return rec
    except Exception as e:  # noqa: BLE001 - evidence capture
        return {"case": name, "model": body["model"], "exception": repr(e)[:400]}


def main() -> int:
    load_env()
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        print("NEBIUS_API_KEY missing (set it in .env)", file=sys.stderr)
        return 2
    client = httpx.Client(headers={"Authorization": f"Bearer {key}"})
    results: list[dict] = []

    t0 = time.perf_counter()
    m = client.get(f"{BASE_URL}/models", timeout=60)
    ids = [x["id"] for x in m.json().get("data", [])] if m.status_code == 200 else []
    results.append(
        {
            "case": "list_models",
            "http_status": m.status_code,
            "latency_s": round(time.perf_counter() - t0, 3),
            "nvidia_models": sorted(i for i in ids if i.lower().startswith("nvidia/")),
        }
    )

    q = "In one sentence: what is 17 * 23? Give the number."
    for tier, model in MODELS.items():
        results.append(
            call(client, f"{tier}_thinking_off", {
                "model": model, "messages": [{"role": "user", "content": q}], "max_tokens": 200,
                "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": False},
            })
        )
    results.append(
        call(client, "fast_thinking_on", {
            "model": MODELS["fast"], "messages": [{"role": "user", "content": q}], "max_tokens": 2000,
            "temperature": 0.6,
        })
    )
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "integer"}, "confidence": {"type": "number"}},
        "required": ["answer", "confidence"], "additionalProperties": False,
    }
    results.append(
        call(client, "fast_json_schema", {
            "model": MODELS["fast"], "max_tokens": 300, "temperature": 0,
            "messages": [{"role": "user", "content": q + " Reply as JSON {answer, confidence}."}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "ans", "schema": schema, "strict": True}},
            "chat_template_kwargs": {"enable_thinking": False},
        })
    )
    results.append(
        call(client, "fast_tool_call", {
            "model": MODELS["fast"], "max_tokens": 400, "temperature": 0,
            "messages": [{"role": "user", "content": "What's 17 times 23? Use the calculator."}],
            "tools": [{"type": "function", "function": {
                "name": "multiply", "description": "Multiply two integers",
                "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                               "required": ["a", "b"]}}}],
            "tool_choice": "auto",
            "chat_template_kwargs": {"enable_thinking": False},
        })
    )

    out = {
        "probe": "nebius_token_factory_nvidia_nemotron",
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "provider": "Nebius Token Factory (OpenAI-compatible chat completions)",
        "base_url": BASE_URL,
        "auth": "Bearer <redacted>",
        "results": results,
    }
    path = ROOT / "docs" / "results" / "nebius_model_runtime_probe.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2))
    for r in results:
        print(json.dumps({k: r.get(k) for k in ("case", "model", "http_status", "latency_s", "content", "has_reasoning_content", "tool_calls", "error")})[:400])
    ok = all(r.get("http_status") == 200 for r in results)
    print("ALL OK" if ok else "SOME CASES FAILED", "->", path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
