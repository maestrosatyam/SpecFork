import asyncio

import httpx
import pytest

from specfork.config import Settings
from specfork.server.main import create_app
from specfork.server.store import RateLimiter
from tests.fake_llm import make_router

SPEC = "Split a restaurant bill evenly among n people. Return how much each person pays, rounded to cents."


def _settings(**kw) -> Settings:
    base = dict(rate_limit_runs=3, daily_budget_usd=1.0, db_path="", public_demo=False)
    base.update(kw)
    return Settings(**base)


async def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def ctx():
    router = make_router()
    app = create_app(_settings(), router=router, web_dist="/nonexistent")
    async with await _client(app) as c:
        yield c, app.state.sf
    await router.aclose()


async def _drain(st):
    await asyncio.wait_for(asyncio.gather(*list(st.tasks)), timeout=30)


async def _wait(c, rid, statuses, timeout=20):
    r = {}
    for _ in range(int(timeout / 0.1)):
        r = (await c.get(f"/api/runs/{rid}")).json()
        if r["status"] in statuses:
            return r
        await asyncio.sleep(0.1)
    raise AssertionError(f"timeout; status={r.get('status')}")


async def test_health_reports_profiles_and_sandbox(ctx):
    c, _ = ctx
    h = (await c.get("/api/health")).json()
    assert h["ok"] and h["llm_configured"] and h["models"]["fast"].startswith("nvidia/")
    assert h["provider_label"] == "Nebius Token Factory" and h["model_labels"]["deep"] == "NVIDIA Nemotron 3 Ultra"
    assert {m["key"] for m in h["available_models"]} == {"lightning", "ultra"}
    assert all("model" in m for m in h["available_models"])
    assert h["sandbox"]["ok"] is True
    p = (await c.get("/api/presets")).json()
    assert len(p) >= 5 and all("spec" in x for x in p)


async def test_run_lifecycle_with_token(ctx):
    c, st = ctx
    r = await c.post("/api/runs", json={"spec": SPEC, "n_samples": 8})
    assert r.status_code == 200
    rid, token = r.json()["id"], r.json()["token"]
    run = await _wait(c, rid, {"awaiting_answers", "error"})
    assert run["status"] == "awaiting_answers", run.get("error")
    answers = {q["id"]: q["options"][0]["id"] for q in run["questions"] if q["kind"] in ("ambiguity", "assumption")}
    assert (await c.post(f"/api/runs/{rid}/answers", json={"answers": answers})).status_code == 403  # no token
    r = await c.post(f"/api/runs/{rid}/answers", json={"answers": answers}, headers={"x-run-token": token})
    assert r.status_code == 200
    run = await _wait(c, rid, {"resolved"})
    assert run["resolution"]["tests_code"].startswith('"""Locked behaviour')
    t = await c.get(f"/api/runs/{rid}/tests.py?module=billing.split")
    assert t.status_code == 200 and "from billing.split import split_bill" in t.text
    assert (await c.get(f"/api/runs/{rid}/tests.py?module=os;rm")).status_code == 422
    md = await c.get(f"/api/runs/{rid}/export.md")
    assert "Clarified spec" in md.text and "Nebius Token Factory" in md.text
    rec = (await c.get(f"/api/runs/{rid}/export.json")).json()
    assert rec["clarified_spec"] and rec["locked_cases"] and rec["prompt_hash"]
    r = await c.post(f"/api/runs/{rid}/converge", json={"n_samples": 4}, headers={"x-run-token": token})
    assert r.status_code == 200
    await _drain(st)
    run = (await c.get(f"/api/runs/{rid}")).json()
    assert run["resolution"]["convergence"]["passed"] == 4
    assert token not in str(run)  # the capability token never appears in public run JSON


async def test_free_text_answer_over_http(ctx):
    c, st = ctx
    r = (await c.post("/api/runs", json={"spec": SPEC, "n_samples": 8})).json()
    run = await _wait(c, r["id"], {"awaiting_answers"})
    qs = [q for q in run["questions"] if q["kind"] in ("ambiguity", "assumption")]
    body = {"answers": {q["id"]: q["options"][0]["id"] for q in qs[1:]}, "other": {qs[0]["id"]: "first people pay extra cents"}}
    assert (await c.post(f"/api/runs/{r['id']}/answers", json={**body, "other": {qs[0]["id"]: "x"}},
                         headers={"x-run-token": r["token"]})).status_code == 422
    assert (await c.post(f"/api/runs/{r['id']}/answers", json=body, headers={"x-run-token": r["token"]})).status_code == 200
    run = await _wait(c, r["id"], {"resolved"})
    assert run["resolution"]["custom_impl_id"]


async def test_model_choice_is_allow_listed(ctx):
    c, _ = ctx
    assert (await c.post("/api/runs", json={"spec": SPEC, "fast_model": "evil/model"})).status_code == 422
    ok = await c.post("/api/runs", json={"spec": SPEC, "n_samples": 4, "fast_model": "lightning", "assumptions": False})
    assert ok.status_code == 200


async def test_validation_and_limits(ctx):
    c, st = ctx
    assert (await c.post("/api/runs", json={"spec": "short"})).status_code == 422
    assert (await c.post("/api/runs", json={"spec": "x" * 2001})).status_code == 422
    assert (await c.post("/api/runs", json={"spec": SPEC, "n_samples": 500})).status_code == 422
    codes = [(await c.post("/api/runs", json={"spec": SPEC, "n_samples": 4})).status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    await _drain(st)
    trav = await c.get("/api/runs/../../etc/passwd")
    assert "root:" not in trav.text
    assert (await c.get("/api/runs/nope")).status_code == 404


async def test_answers_payload_bounded(ctx):
    c, st = ctx
    r = (await c.post("/api/runs", json={"spec": SPEC, "n_samples": 4})).json()
    await _drain(st)
    h = {"x-run-token": r["token"]}
    big = {f"q{i}": "x" for i in range(25)}
    assert (await c.post(f"/api/runs/{r['id']}/answers", json={"answers": big}, headers=h)).status_code == 422
    assert (await c.post(f"/api/runs/{r['id']}/answers", json={"answers": {"q0": "x" * 5000}}, headers=h)).status_code == 422


async def test_runs_listing_is_private(ctx):
    c, st = ctx
    rid = (await c.post("/api/runs", json={"spec": SPEC, "n_samples": 4})).json()["id"]
    await _drain(st)
    assert rid not in {r["id"] for r in (await c.get("/api/runs")).json()}
    assert rid in {r["id"] for r in (await c.get(f"/api/runs?ids={rid}")).json()}


async def test_rate_limit_uses_rightmost_forwarded_for(ctx):
    c, st = ctx
    codes = []
    for k in range(4):  # attacker rotates a spoofed left-most XFF value; Cloud Run appends the real IP last
        r = await c.post("/api/runs", json={"spec": SPEC, "n_samples": 4},
                         headers={"x-forwarded-for": f"10.0.0.{k}, 203.0.113.7"})
        codes.append(r.status_code)
    assert codes[3] == 429
    await _drain(st)


async def test_public_demo_mode():
    router = make_router()
    app = create_app(_settings(public_demo=True), router=router, web_dist="/nonexistent")
    async with await _client(app) as c:
        r = await c.get("/api/health")
        assert r.json()["public_demo"] is True
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert '"openapi"' not in (await c.get("/openapi.json")).text
    await router.aclose()


async def test_openapi_served_outside_demo(ctx):
    c, _ = ctx
    spec = (await c.get("/openapi.json")).json()
    assert "/api/runs" in spec["paths"]


async def test_unconfigured_returns_503():
    router = make_router(key="")
    app = create_app(_settings(), router=router, web_dist="/nonexistent")
    async with await _client(app) as c:
        assert (await c.post("/api/runs", json={"spec": SPEC})).status_code == 503
    await router.aclose()


async def test_sqlite_store_survives_restart(tmp_path):
    db = str(tmp_path / "runs.db")
    router = make_router()
    app = create_app(_settings(db_path=db), router=router, web_dist="/nonexistent")
    async with await _client(app) as c:
        r = (await c.post("/api/runs", json={"spec": SPEC, "n_samples": 4})).json()
        await _drain(app.state.sf)
    app2 = create_app(_settings(db_path=db), router=router, web_dist="/nonexistent")  # "restarted" server
    async with await _client(app2) as c:
        assert (await c.get(f"/api/runs/{r['id']}")).json()["status"] == "awaiting_answers"
        assert app2.state.sf.store.check_token(r["id"], r["token"])
    await router.aclose()


def test_budget_cap():
    lim = RateLimiter(per_window=100, daily_budget_usd=0.01)
    assert lim.check("a") is None
    lim.add_spend(0.02)
    assert "budget" in lim.check("a")
