"""SpecFork HTTP API (FastAPI) and static frontend.

Create the app with :func:`create_app` (``uvicorn --factory specfork.server.main:create_app``). Importing this
module has no side effects; configuration comes from an explicit :class:`specfork.config.Settings`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .. import __version__, sandbox
from ..config import Settings
from ..llm import ModelRouter
from ..pipeline import PipelineError, SpecFork, new_run, render_tests, summarize
from ..presets import PRESETS
from ..registry import ModelProfile, Registry, RegistryError
from .store import RateLimiter, RunStore

ROOT = Path(__file__).resolve().parents[2]
MAX_SPEC_CHARS = 2000
ACTIVE = {"running", "resolving", "converging"}
MAX_SSE_PER_CLIENT = 4
# Spend is reserved when work is admitted (so concurrent requests cannot overshoot the daily cap)
# and trued up with the metered cost when the work finishes.
RESERVE_RUN_USD, RESERVE_ANSWER_USD, RESERVE_CONVERGE_USD = 0.08, 0.03, 0.04

SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
                                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@dataclass
class State:
    settings: Settings
    registry: Registry
    router: ModelRouter
    engine: SpecFork
    store: RunStore
    limiter: RateLimiter
    answer_limiter: RateLimiter
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    sandbox_status: dict[str, Any] = field(default_factory=dict)
    sse_open: int = 0
    sse_by_client: dict[str, int] = field(default_factory=dict)


def _harden_process() -> None:
    """Make /proc/<pid>/environ and memory of this server unreadable to the sandboxed children
    (they run as the same uid). PR_SET_DUMPABLE=0 re-owns /proc/<pid>/* to root."""
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE = 4
    except Exception:  # noqa: BLE001 - non-Linux dev machines
        pass


# ---------------------------------------------------------------- request models

class CreateRun(BaseModel):
    spec: str = Field(min_length=10, max_length=MAX_SPEC_CHARS)
    n_samples: int = Field(default=24, ge=4, le=40)
    preset_id: str | None = Field(default=None, max_length=40)
    fast_model: str | None = Field(default=None, max_length=64)
    deep_model: str | None = Field(default=None, max_length=64)
    assumptions: bool | None = None
    exception_types: bool | None = None


class Answers(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict, max_length=20)
    other: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("answers")
    @classmethod
    def _small(cls, v: dict[str, str]) -> dict[str, str]:
        if any(len(k) > 32 or len(x) > 64 for k, x in v.items()):
            raise ValueError("answer ids too long")
        return v

    @field_validator("other")
    @classmethod
    def _text(cls, v: dict[str, str]) -> dict[str, str]:
        if any(len(k) > 32 or not (3 <= len(x.strip()) <= 300) for k, x in v.items()):
            raise ValueError("free-text answers must be 3-300 characters")
        return {k: x.strip() for k, x in v.items()}


class Converge(BaseModel):
    n_samples: int | None = Field(default=None, ge=4, le=40)


# ---------------------------------------------------------------- helpers

def _client_id(request: Request) -> str:
    """Client address for rate limiting. Cloud Run's front end APPENDS the real client address to
    X-Forwarded-For, so only the right-most entry is trustworthy (left entries are client-supplied)."""
    fwd = request.headers.get("x-forwarded-for", "")
    last = fwd.split(",")[-1].strip() if fwd else ""
    return last[:64] or (request.client.host if request.client else "unknown")


def _st(request: Request) -> State:
    return request.app.state.sf


def _get(st: State, run_id: str) -> dict[str, Any]:
    if not run_id.replace("-", "").replace("_", "").isalnum() or len(run_id) > 64:
        raise HTTPException(404, "run not found")
    run = st.store.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


def _require_token(st: State, run: dict[str, Any], token: str | None) -> None:
    if not st.store.check_token(run["id"], token):
        raise HTTPException(403, "Only the browser that started this run can answer or re-fork it. "
                                 "Fork the spec to run your own.")


def _spawn(st: State, coro: Any, run: dict[str, Any], reserve_usd: float = 0.0) -> None:
    cost0 = run["metrics"]["total_cost_usd"]
    st.limiter.add_spend(reserve_usd)

    async def wrapper() -> None:
        try:
            await coro
        finally:
            st.limiter.add_spend(run["metrics"]["total_cost_usd"] - cost0 - reserve_usd)
            st.store.touch(run)
            st.store.persist(run)

    t = asyncio.create_task(wrapper())
    st.tasks.add(t)
    t.add_done_callback(st.tasks.discard)


def allowed_models(st: State, role: str) -> list[ModelProfile]:
    """Models a visitor may pick for a role: configured, and priced when this is a public demo."""
    out = []
    for p in st.registry.for_role(role):
        if not st.router.configured(p.key):
            continue
        if st.settings.public_demo and p.price_per_m is None:
            continue
        out.append(p)
    return out


def _pick(st: State, role: str, requested: str | None, default: str) -> ModelProfile:
    if requested is None:
        return st.registry.get(default)
    allowed = {p.key: p for p in allowed_models(st, role)}
    if requested not in allowed:
        raise HTTPException(422, f"model '{requested}' is not available for {role} "
                                 f"(choose from: {', '.join(sorted(allowed))})")
    return allowed[requested]


def _label(st: State, model: str) -> tuple[str, str]:
    try:
        p = st.registry.get(model)
        return p.display, p.provider_label
    except RegistryError:
        return model, ""


# ---------------------------------------------------------------- routes

api = APIRouter()


@api.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    st = _st(request)
    if not st.sandbox_status:
        st.sandbox_status.update(await sandbox.selftest())
    fast, deep = st.registry.get(st.settings.fast_model), st.registry.get(st.settings.deep_model)
    avail: dict[str, ModelProfile] = {}
    for role in ("fast", "deep"):
        for p in allowed_models(st, role):
            avail[p.key] = p
    return {
        "ok": True, "version": __version__,
        "llm_configured": st.router.configured(fast.key) and st.router.configured(deep.key),
        "provider": fast.provider_label, "provider_label": fast.provider_label,
        "models": {"fast": fast.model, "deep": deep.model},
        "model_labels": {"fast": fast.display, "deep": deep.display},
        "available_models": [p.public() for p in avail.values()],
        "public_demo": st.settings.public_demo,
        "sandbox": {"ok": st.sandbox_status.get("ok"), "net_isolated": st.sandbox_status.get("net_isolated")},
    }


@api.get("/api/presets")
async def presets(request: Request) -> list[dict[str, Any]]:
    st = _st(request)
    samples = {r.get("preset_id"): r["id"] for r in st.store.runs.values() if r.get("is_sample") and r.get("preset_id")}
    return [{**p, "sample_run_id": samples.get(p["id"])} for p in PRESETS]


@api.get("/api/runs")
async def list_runs(request: Request, ids: str = "") -> list[dict[str, Any]]:
    """Recorded sample runs plus the runs whose ids the caller already knows (kept in its own browser).
    Other visitors' runs are never listed."""
    st = _st(request)
    wanted = {i for i in ids.split(",")[:20] if i and len(i) <= 64 and i.replace("-", "").replace("_", "").isalnum()}
    for i in wanted:
        st.store.get(i)
    out = [r for r in st.store.recent(1000) if r.get("is_sample") or r["id"] in wanted]
    return [summarize(r) for r in out[:40]]


@api.post("/api/runs")
async def create_run(body: CreateRun, request: Request) -> dict[str, str]:
    st = _st(request)
    fast = _pick(st, "fast", body.fast_model, st.settings.fast_model)
    deep = _pick(st, "deep", body.deep_model, st.settings.deep_model)
    if not (st.router.configured(fast.key) and st.router.configured(deep.key)):
        raise HTTPException(503, "Inference is not configured on this server (API key missing).")
    msg = st.limiter.check(_client_id(request))
    if msg:
        raise HTTPException(429, msg)
    spec = body.spec.replace("\x00", "").strip()
    implementers = ([fast.model] if body.fast_model else
                    [st.registry.get(k).model for k in st.settings.implementer_keys])
    run = new_run(secrets.token_urlsafe(12), spec, body.n_samples, body.preset_id, fast.model, deep.model,
                  implementers=implementers,
                  assumptions=st.settings.assumptions if body.assumptions is None else body.assumptions,
                  exception_types=st.settings.exception_types if body.exception_types is None else body.exception_types,
                  adaptive_n=st.settings.adaptive_n, probe_rounds=st.settings.probe_rounds)
    token = secrets.token_urlsafe(24)
    st.store.add(run)
    st.store.set_token(run["id"], token)
    _spawn(st, st.engine.run_all(run), run, RESERVE_RUN_USD)
    return {"id": run["id"], "token": token}


@api.get("/api/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    return _get(_st(request), run_id)


@api.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    st = _st(request)
    run = _get(st, run_id)
    cid = _client_id(request)
    if st.sse_open >= st.settings.max_sse or st.sse_by_client.get(cid, 0) >= MAX_SSE_PER_CLIENT:
        raise HTTPException(503, "Too many open event streams; the client will fall back to polling.")
    st.sse_open += 1
    st.sse_by_client[cid] = st.sse_by_client.get(cid, 0) + 1

    async def gen():
        try:
            async for chunk in _gen():
                yield chunk
        finally:
            st.sse_open -= 1
            st.sse_by_client[cid] -= 1
            if st.sse_by_client[cid] <= 0:
                st.sse_by_client.pop(cid, None)

    async def _gen():
        last = -1
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            v = st.store.versions[run_id]
            if v != last:
                last = v
                idle = 0
                yield f"event: snapshot\ndata: {json.dumps(run)}\n\n"
                if run["status"] not in ACTIVE:
                    yield "event: end\ndata: {}\n\n"
                    return
            ev = st.store.event(run_id)
            ev.clear()
            try:
                await asyncio.wait_for(ev.wait(), timeout=15)
            except TimeoutError:
                idle += 1
                yield ": keepalive\n\n"
                if idle > 40:
                    return
            await asyncio.sleep(0.25)  # throttle to <= 4 snapshots/s

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@api.post("/api/runs/{run_id}/answers")
async def answer(run_id: str, body: Answers, request: Request,
                 x_run_token: str | None = Header(default=None)) -> dict[str, Any]:
    st = _st(request)
    run = _get(st, run_id)
    if run.get("is_sample"):
        raise HTTPException(409, "This is a recorded sample run. Fork the spec to run it live.")
    _require_token(st, run, x_run_token)
    if run["status"] not in ("awaiting_answers", "resolved"):
        raise HTTPException(409, f"run is {run['status']}")
    msg = st.answer_limiter.check(_client_id(request)) or st.limiter.budget_message()
    if msg:
        raise HTTPException(429, msg)
    run.pop("error", None)
    run["status"] = "resolving"
    st.store.touch(run)

    async def go() -> None:
        try:
            await st.engine.resolve(run, body.answers, body.other)
        except PipelineError:
            pass

    _spawn(st, go(), run, RESERVE_ANSWER_USD)
    return run


@api.post("/api/runs/{run_id}/converge")
async def converge(run_id: str, body: Converge, request: Request,
                   x_run_token: str | None = Header(default=None)) -> dict[str, Any]:
    st = _st(request)
    run = _get(st, run_id)
    if run.get("is_sample"):
        raise HTTPException(409, "This is a recorded sample run. Fork the spec to run it live.")
    if run["status"] != "resolved" or not run.get("resolution"):
        raise HTTPException(409, "resolve the run first")
    _require_token(st, run, x_run_token)
    msg = st.limiter.check(_client_id(request))
    if msg:
        raise HTTPException(429, msg)
    run["status"] = "converging"
    st.store.touch(run)
    _spawn(st, st.engine.converge(run, body.n_samples or run["settings"]["n_samples"]), run, RESERVE_CONVERGE_USD)
    return run


@api.get("/api/runs/{run_id}/tests.py", response_class=PlainTextResponse)
async def tests_file(run_id: str, request: Request, module: str = "solution") -> str:
    run = _get(_st(request), run_id)
    if not run.get("resolution"):
        raise HTTPException(409, "not resolved yet")
    if module == "solution":
        return run["resolution"]["tests_code"]
    if len(module) > 120 or not all(part.isidentifier() for part in module.split(".")):
        raise HTTPException(422, "module must be a dotted Python module path")
    res = run["resolution"]
    return render_tests(run["signature"], res["locked_cases"], res["clarified_spec"], module=module)


@api.get("/api/runs/{run_id}/export.json")
async def export_json(run_id: str, request: Request) -> dict[str, Any]:
    run = _get(_st(request), run_id)
    if not run.get("resolution"):
        raise HTTPException(409, "not resolved yet")
    return decision_record(run)


@api.get("/api/runs/{run_id}/export.md", response_class=PlainTextResponse)
async def export_md(run_id: str, request: Request) -> str:
    st = _st(request)
    run = _get(st, run_id)
    res = run.get("resolution")
    if not res:
        raise HTTPException(409, "not resolved yet")
    conv = res.get("convergence") or {}
    label, provider = _label(st, run["settings"]["fast_model"])
    via = f" via {provider}" if provider else ""
    lines = [
        f"# SpecFork result — `{run['signature']['name']}`", "",
        "## Original spec", "", run["spec"], "",
        "## Clarified spec", "", res["clarified_spec"], "",
        "## Decisions", "", *[f"- {d}" for d in res["decisions"]], "",
        "## Evidence", "",
        f"- Implementations generated: {len(run['implementations'])} by {label} (`{run['settings']['fast_model']}`){via}",
        f"- Distinct behaviours found: {len([c for c in run['clusters'] if c['kind'] == 'behavior'])}",
        f"- Agreement with chosen behaviour before clarification: {res['agreement_before']:.0%}",
    ]
    if conv.get("status") == "done":
        lines.append(f"- Agreement after clarification (fresh re-fork): {conv['agreement_after']:.0%} "
                     f"({conv['passed']}/{conv.get('executed', conv['n'])})")
    lines += ["", "## Reference implementation", "", "```python", res["reference_code"], "```", "",
              "## Locked tests (pytest)", "", "```python", res["tests_code"], "```", ""]
    return "\n".join(lines)


def decision_record(run: dict[str, Any]) -> dict[str, Any]:
    """Machine-readable result: commit it next to the code (e.g. as .specfork.json)."""
    res = run["resolution"]
    q_by_id = {q["id"]: q for q in run["questions"]}
    decisions = []
    for qid, oid in (res.get("answers") or {}).items():
        q = q_by_id.get(qid)
        if not q or not oid:
            continue
        opt = next((o for o in q["options"] if o["id"] == oid), None)
        decisions.append({"question": q["text"], "kind": q["kind"], "answer": opt["label"] if opt else oid,
                          "custom": bool(opt and opt.get("is_custom"))})
    return {
        "specfork_version": __version__, "run_id": run["id"], "spec": run["spec"],
        "clarified_spec": res["clarified_spec"], "signature": run["signature"], "decisions": decisions,
        "locked_cases": [{"args": c["args"], "expected": c["expected_repr"]} for c in res["locked_cases"]],
        "agreement_before": res["agreement_before"],
        "agreement_after": (res.get("convergence") or {}).get("agreement_after"),
        "models": {"fast": run["settings"]["fast_model"], "deep": run["settings"]["deep_model"]},
        "prompt_version": run["settings"].get("prompt_version"), "prompt_hash": run["settings"].get("prompt_hash"),
    }


# ---------------------------------------------------------------- factory

def create_app(settings: Settings | None = None, router: ModelRouter | None = None,
               web_dist: str | Path | None = None) -> FastAPI:
    """Build the FastAPI app. With no arguments, settings come from the environment / ``.env``."""
    settings = settings or Settings.load()
    registry = router.registry if router is not None else Registry.load(settings.models_file)
    if router is None:
        router = ModelRouter(registry, settings.api_keys, max_concurrency=settings.llm_concurrency,
                             default_model=settings.fast_model)
    for key in (settings.fast_model, settings.deep_model, *settings.implementer_keys):
        registry.get(key)  # fail fast on unknown profiles
    if settings.public_demo:
        _harden_process()
        for key in (settings.fast_model, settings.deep_model, *settings.implementer_keys):
            if registry.get(key).price_per_m is None:
                raise RegistryError(f"public demo refuses unpriced model profile '{key}' (the budget cap needs prices)")
    sandbox.configure(settings.sandbox_require_isolation, settings.sandbox_concurrency)

    public = settings.public_demo

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        st: State = app.state.sf
        st.sandbox_status.update(await sandbox.selftest())
        if not st.sandbox_status.get("net_isolated"):
            logging.getLogger("uvicorn.error").warning(
                "SpecFork sandbox: network isolation is NOT available on this host; model-written code runs with "
                "weaker isolation (set SANDBOX_REQUIRE_ISOLATION=1 to refuse, or run on Linux/Docker).")
        yield

    app = FastAPI(title="SpecFork", version=__version__, docs_url=None if public else "/docs",
                  redoc_url=None, openapi_url=None if public else "/openapi.json", lifespan=lifespan)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path != "/docs":  # Swagger UI (served only outside demo mode) loads its own scripts
            for k, v in SECURITY_HEADERS.items():
                response.headers.setdefault(k, v)
        return response

    store = RunStore(None if public or not settings.db_path else settings.db_path)
    state = State(
        settings=settings, registry=registry, router=router, store=store,
        engine=SpecFork(router, store.touch, frame_thinking=settings.frame_thinking,
                        assumption_min_confidence=settings.assumption_min_confidence,
                        max_assumptions=settings.max_assumptions,
                        assumption_requires_witness=settings.assumption_requires_witness),
        limiter=RateLimiter(per_window=settings.rate_limit_runs, window_s=settings.rate_limit_window_s,
                            daily_budget_usd=settings.daily_budget_usd),
        answer_limiter=RateLimiter(per_window=20, window_s=600, daily_budget_usd=float("inf")),
    )
    app.state.sf = state
    app.include_router(api)


    candidates = [Path(web_dist)] if web_dist else [
        Path(os.environ["WEB_DIST"]) if os.environ.get("WEB_DIST") else None,
        ROOT / "web" / "dist",                              # source checkout
        Path(__file__).resolve().parents[1] / "_web",       # built into the wheel by `make package`
    ]
    dist = next((c for c in candidates if c is not None and (c / "index.html").exists()), Path("/nonexistent"))
    if dist.exists():
        if (dist / "assets").exists():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app
