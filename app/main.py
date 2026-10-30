"""SpecFork HTTP API (FastAPI). Serves the built frontend from web/dist at `/`."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .llm import MODEL_DEEP, MODEL_FAST, NebiusClient
from .pipeline import PipelineError, SpecFork, new_run, summarize
from .presets import PRESETS
from .store import RateLimiter, RunStore

VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[1]
WEB_DIST = Path(os.environ.get("WEB_DIST", ROOT / "web" / "dist"))
MAX_SPEC_CHARS = 2000


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _harden_process() -> None:
    """Make /proc/<pid>/environ and memory of this server unreadable to the sandboxed children
    (they run as the same uid). PR_SET_DUMPABLE=0 re-owns /proc/<pid>/* to root."""
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE = 4
    except Exception:  # noqa: BLE001 - non-Linux dev machines
        pass


_harden_process()

app = FastAPI(title="SpecFork", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)

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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response
store = RunStore(os.environ.get("RUNS_DIR", "/tmp/specfork-runs"))
limiter = RateLimiter(
    per_window=int(os.environ.get("RATE_LIMIT_RUNS", "6")),
    window_s=float(os.environ.get("RATE_LIMIT_WINDOW_S", "600")),
    daily_budget_usd=float(os.environ.get("DAILY_BUDGET_USD", "5")),
)
client = NebiusClient(api_key=os.environ.pop("NEBIUS_API_KEY", ""),  # keep the key out of os.environ
                      max_concurrency=int(os.environ.get("LLM_CONCURRENCY", "16")))
_tasks: set[asyncio.Task[Any]] = set()


def _notify(run: dict[str, Any]) -> None:
    store.touch(run)


engine = SpecFork(client, _notify)


class CreateRun(BaseModel):
    spec: str = Field(min_length=10, max_length=MAX_SPEC_CHARS)
    n_samples: int = Field(default=24, ge=4, le=40)
    preset_id: str | None = Field(default=None, max_length=40)


class Answers(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class Converge(BaseModel):
    n_samples: int | None = Field(default=None, ge=4, le=40)


def _client_id(request: Request) -> str:
    """Client address for rate limiting. Cloud Run's front end APPENDS the real client address to
    X-Forwarded-For, so only the right-most entry is trustworthy (left entries are client-supplied)."""
    fwd = request.headers.get("x-forwarded-for", "")
    last = fwd.split(",")[-1].strip() if fwd else ""
    return last[:64] or (request.client.host if request.client else "unknown")


def _spawn(coro: Any, run: dict[str, Any]) -> None:
    cost0 = run["metrics"]["total_cost_usd"]

    async def wrapper() -> None:
        try:
            await coro
        finally:
            limiter.add_spend(run["metrics"]["total_cost_usd"] - cost0)
            store.touch(run)
            store.persist(run)

    t = asyncio.create_task(wrapper())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def _get(run_id: str) -> dict[str, Any]:
    if not run_id.replace("-", "").replace("_", "").isalnum() or len(run_id) > 64:
        raise HTTPException(404, "run not found")
    run = store.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "llm_configured": client.configured, "models": {"fast": MODEL_FAST, "deep": MODEL_DEEP},
            "provider": "Nebius Token Factory", "version": VERSION}


@app.get("/api/presets")
async def presets() -> list[dict[str, Any]]:
    samples = {r.get("preset_id"): r["id"] for r in store.runs.values() if r.get("is_sample") and r.get("preset_id")}
    return [{**p, "sample_run_id": samples.get(p["id"])} for p in PRESETS]


@app.get("/api/runs")
async def list_runs(ids: str = "") -> list[dict[str, Any]]:
    """Recorded sample runs plus the runs whose ids the caller already knows (kept in its own browser).
    Other visitors' runs are never listed."""
    wanted = {i for i in ids.split(",")[:20] if i and len(i) <= 64 and i.replace("-", "").replace("_", "").isalnum()}
    out = [r for r in store.recent(1000) if r.get("is_sample") or r["id"] in wanted]
    return [summarize(r) for r in out[:40]]


@app.post("/api/runs")
async def create_run(body: CreateRun, request: Request) -> dict[str, str]:
    if not client.configured:
        raise HTTPException(503, "Inference is not configured on this server (NEBIUS_API_KEY missing).")
    msg = limiter.check(_client_id(request))
    if msg:
        raise HTTPException(429, msg)
    spec = body.spec.replace("\x00", "").strip()
    run = new_run(secrets.token_urlsafe(9), spec, body.n_samples, body.preset_id)
    store.add(run)
    _spawn(engine.run_all(run), run)
    return {"id": run["id"]}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    return _get(run_id)


ACTIVE = {"running", "resolving", "converging"}
MAX_SSE = int(os.environ.get("MAX_SSE", "200"))
_sse_open = [0]


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    run = _get(run_id)
    if _sse_open[0] >= MAX_SSE:
        raise HTTPException(503, "Too many open event streams; the client will fall back to polling.")

    async def gen():
        _sse_open[0] += 1
        try:
            async for chunk in _gen():
                yield chunk
        finally:
            _sse_open[0] -= 1

    async def _gen():
        last = -1
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            v = store.versions[run_id]
            if v != last:
                last = v
                idle = 0
                yield f"event: snapshot\ndata: {json.dumps(run)}\n\n"
                if run["status"] not in ACTIVE:
                    yield "event: end\ndata: {}\n\n"
                    return
            ev = store.event(run_id)
            ev.clear()
            try:
                await asyncio.wait_for(ev.wait(), timeout=15)
            except asyncio.TimeoutError:
                idle += 1
                yield ": keepalive\n\n"
                if idle > 40:
                    return
            await asyncio.sleep(0.25)  # throttle to ≤4 snapshots/s

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/runs/{run_id}/answers")
async def answer(run_id: str, body: Answers) -> dict[str, Any]:
    run = _get(run_id)
    if run.get("is_sample"):
        raise HTTPException(409, "This is a recorded sample run. Fork the spec to run it live.")
    if run["status"] not in ("awaiting_answers", "resolved"):
        raise HTTPException(409, f"run is {run['status']}")
    run.pop("error", None)
    run["status"] = "resolving"
    store.touch(run)

    async def go() -> None:
        try:
            await engine.resolve(run, body.answers)
        except PipelineError:
            pass

    _spawn(go(), run)
    return run


@app.post("/api/runs/{run_id}/converge")
async def converge(run_id: str, body: Converge, request: Request) -> dict[str, Any]:
    run = _get(run_id)
    if run.get("is_sample"):
        raise HTTPException(409, "This is a recorded sample run. Fork the spec to run it live.")
    if run["status"] != "resolved" or not run.get("resolution"):
        raise HTTPException(409, "resolve the run first")
    msg = limiter.check(_client_id(request))
    if msg:
        raise HTTPException(429, msg)
    run["status"] = "converging"
    store.touch(run)
    _spawn(engine.converge(run, body.n_samples or run["settings"]["n_samples"]), run)
    return run


@app.get("/api/runs/{run_id}/tests.py", response_class=PlainTextResponse)
async def tests_file(run_id: str) -> str:
    run = _get(run_id)
    if not run.get("resolution"):
        raise HTTPException(409, "not resolved yet")
    return run["resolution"]["tests_code"]


@app.get("/api/runs/{run_id}/export.md", response_class=PlainTextResponse)
async def export_md(run_id: str) -> str:
    run = _get(run_id)
    res = run.get("resolution")
    if not res:
        raise HTTPException(409, "not resolved yet")
    conv = res.get("convergence") or {}
    lines = [
        f"# SpecFork result — `{run['signature']['name']}`", "",
        "## Original spec", "", run["spec"], "",
        "## Clarified spec", "", res["clarified_spec"], "",
        "## Decisions", "", *[f"- {d}" for d in res["decisions"]], "",
        "## Evidence", "",
        f"- Implementations generated: {len(run['implementations'])} by `{run['settings']['fast_model']}` via Nebius Token Factory",
        f"- Distinct behaviours found: {len([c for c in run['clusters'] if c['kind'] == 'behavior'])}",
        f"- Agreement with chosen behaviour before clarification: {res['agreement_before']:.0%}",
    ]
    if conv.get("status") == "done":
        lines.append(f"- Agreement after clarification (fresh re-fork): {conv['agreement_after']:.0%} ({conv['passed']}/{conv.get('executed', conv['n'])})")
    lines += ["", "## Reference implementation", "", "```python", res["reference_code"], "```", "",
              "## Locked tests (pytest)", "", "```python", res["tests_code"], "```", ""]
    return "\n".join(lines)


# ---- frontend
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets") if (WEB_DIST / "assets").exists() else None

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        f = (WEB_DIST / path).resolve()
        if path and f.is_file() and WEB_DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
