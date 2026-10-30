#!/usr/bin/env python3
"""Write docs/openapi.json from the FastAPI app (tests fail if it drifts from the code)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfork.config import Settings  # noqa: E402
from specfork.server.main import create_app  # noqa: E402
from tests.fake_llm import make_router  # noqa: E402


def schema() -> dict:
    app = create_app(Settings(db_path="", public_demo=False), router=make_router(), web_dist="/nonexistent")
    return app.openapi()


if __name__ == "__main__":
    (ROOT / "docs" / "openapi.json").write_text(json.dumps(schema(), indent=1, sort_keys=True) + "\n")
    print("wrote docs/openapi.json")
