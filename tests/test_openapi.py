import json
from pathlib import Path

from scripts.gen_openapi import schema


def test_openapi_document_matches_code():
    committed = json.loads(Path("docs/openapi.json").read_text())
    assert committed == json.loads(json.dumps(schema(), sort_keys=True)), "run `make openapi` and commit docs/openapi.json"
