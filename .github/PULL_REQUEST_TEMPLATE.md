## Summary

<!-- What does this change and why? Link the issue it addresses, e.g. "Fixes #123". -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Model provider profile / preset
- [ ] Sandbox or other security-sensitive change
- [ ] Refactor / internal cleanup
- [ ] Docs, CI or tooling

## How was this tested?

<!-- Commands you ran and what you checked. Live-model checks (e.g. `make probe`, `make eval`) are welcome but
     must not be required for CI: tests stay offline and use tests/fake_llm.py. -->

## Checklist

- [ ] `make lint` and `make test` pass locally (`uv run ruff check .`, `uv run pytest -q`, `cd web && npm test`)
- [ ] `cd web && npm run typecheck` passes (if the frontend changed)
- [ ] New behaviour is covered by tests
- [ ] Decisions stay in code; the model only explains ("code decides, the model explains")
- [ ] Sandbox / security-sensitive changes include regression tests in `tests/test_sandbox.py` and an update to `docs/SECURITY.md`
- [ ] User-visible changes are noted under `## [Unreleased]` in `CHANGELOG.md`
- [ ] No secrets, API keys or `.env` contents are included
