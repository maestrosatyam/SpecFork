# HTTP API

The HTTP API is described by the generated OpenAPI document [`docs/openapi.json`](openapi.json) (regenerate with
`make openapi`; `tests/test_openapi.py` fails when it drifts from the code). A running server outside
public-demo mode also serves it at `/openapi.json` with interactive docs at `/docs`.

Summary (see [ARCHITECTURE.md](ARCHITECTURE.md) for the run record and the UX flow):

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | version, model profiles and labels, `available_models`, `public_demo`, sandbox isolation |
| GET | `/api/presets` | example specs with recorded sample runs |
| POST | `/api/runs` | `{spec, n_samples 4..40, preset_id?, fast_model?, deep_model?, assumptions?}` → `{id, token}` |
| GET | `/api/runs?ids=a,b` | recorded samples plus the given run ids (never other visitors' runs) |
| GET | `/api/runs/{id}` | the run record |
| GET | `/api/runs/{id}/events` | server-sent events: `snapshot` (full run JSON), `end` |
| POST | `/api/runs/{id}/answers` | header `X-Run-Token`; `{answers: {qid: option_id}, other: {qid: free text}}` |
| POST | `/api/runs/{id}/converge` | header `X-Run-Token`; `{n_samples?}` |
| GET | `/api/runs/{id}/tests.py?module=pkg.mod` | locked pytest file |
| GET | `/api/runs/{id}/export.md` / `export.json` | human-readable report / machine-readable decision record |
