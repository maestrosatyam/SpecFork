import asyncio

import httpx
import pytest

from app import main
from app.llm import NebiusClient
from app.store import RateLimiter
from tests.fake_llm import make_transport

SPEC = "Split a restaurant bill evenly among n people. Return how much each person pays, rounded to cents."


@pytest.fixture
async def api(monkeypatch):
    fake = NebiusClient(api_key="test", transport=make_transport())
    monkeypatch.setattr(main, "client", fake)
    monkeypatch.setattr(main.engine, "client", fake)
    monkeypatch.setattr(main, "limiter", RateLimiter(per_window=3, window_s=600, daily_budget_usd=1.0))
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await fake.aclose()


async def _wait(c, rid, statuses, timeout=20):
    for _ in range(int(timeout / 0.1)):
        r = (await c.get(f"/api/runs/{rid}")).json()
        if r["status"] in statuses:
            return r
        await asyncio.sleep(0.1)
    raise AssertionError(f"timeout; status={r['status']}")


async def test_health_and_presets(api):
    h = (await api.get("/api/health")).json()
    assert h["ok"] and h["llm_configured"] and h["models"]["fast"].startswith("nvidia/")
    p = (await api.get("/api/presets")).json()
    assert len(p) >= 5 and all("spec" in x for x in p)


async def test_run_lifecycle(api):
    r = await api.post("/api/runs", json={"spec": SPEC, "n_samples": 8})
    assert r.status_code == 200
    rid = r.json()["id"]
    run = await _wait(api, rid, {"awaiting_answers", "error"})
    assert run["status"] == "awaiting_answers", run.get("error")
    answers = {q["id"]: q["options"][0]["id"] for q in run["questions"] if q["kind"] in ("ambiguity", "assumption")}
    r = await api.post(f"/api/runs/{rid}/answers", json={"answers": answers})
    assert r.status_code == 200
    run = await _wait(api, rid, {"resolved"})
    assert run["resolution"]["tests_code"].startswith('"""Locked behaviour')
    t = await api.get(f"/api/runs/{rid}/tests.py")
    assert t.status_code == 200 and "def test_split_bill" in t.text
    md = await api.get(f"/api/runs/{rid}/export.md")
    assert "Clarified spec" in md.text and "Nebius Token Factory" in md.text
    r = await api.post(f"/api/runs/{rid}/converge", json={"n_samples": 4})
    assert r.status_code == 200
    for _ in range(200):
        run = (await api.get(f"/api/runs/{rid}")).json()
        if run["status"] == "resolved" and (run["resolution"].get("convergence") or {}).get("status") == "done":
            break
        await asyncio.sleep(0.1)
    assert run["resolution"]["convergence"]["passed"] == 4


async def test_validation_and_limits(api):
    assert (await api.post("/api/runs", json={"spec": "short"})).status_code == 422
    assert (await api.post("/api/runs", json={"spec": "x" * 2001})).status_code == 422
    assert (await api.post("/api/runs", json={"spec": SPEC, "n_samples": 500})).status_code == 422
    codes = [(await api.post("/api/runs", json={"spec": SPEC, "n_samples": 4})).status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    await asyncio.wait_for(asyncio.gather(*list(main._tasks)), timeout=30)  # let background runs finish
    trav = await api.get("/api/runs/../../etc/passwd")
    assert "root:" not in trav.text  # normalised to the SPA (or 404), never the file
    assert (await api.get("/api/runs/nope")).status_code == 404


async def test_unconfigured_returns_503(api, monkeypatch):
    monkeypatch.setattr(main, "client", NebiusClient(api_key=""))
    assert (await api.post("/api/runs", json={"spec": SPEC})).status_code == 503


def test_budget_cap():
    lim = RateLimiter(per_window=100, daily_budget_usd=0.01)
    assert lim.check("a") is None
    lim.add_spend(0.02)
    assert "budget" in lim.check("a")


async def test_security_headers_and_no_docs(api):
    r = await api.get("/api/health")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert (await api.get("/docs")).status_code in (404, 200) and "swagger" not in (await api.get("/docs")).text.lower()
    assert (await api.get("/openapi.json")).headers.get("content-type", "").startswith("application/json") is False


async def test_runs_listing_is_private(api):
    rid = (await api.post("/api/runs", json={"spec": SPEC, "n_samples": 4})).json()["id"]
    await asyncio.wait_for(asyncio.gather(*list(main._tasks)), timeout=30)
    listed = {r["id"] for r in (await api.get("/api/runs")).json()}
    assert rid not in listed  # other visitors' runs are not listed
    mine = {r["id"] for r in (await api.get(f"/api/runs?ids={rid}")).json()}
    assert rid in mine


async def test_rate_limit_uses_rightmost_forwarded_for(api):
    codes = []
    for k in range(4):  # attacker rotates a spoofed left-most XFF value; Cloud Run appends the real IP last
        r = await api.post("/api/runs", json={"spec": SPEC, "n_samples": 4},
                           headers={"x-forwarded-for": f"10.0.0.{k}, 203.0.113.7"})
        codes.append(r.status_code)
    assert codes[3] == 429
    await asyncio.wait_for(asyncio.gather(*list(main._tasks)), timeout=30)
