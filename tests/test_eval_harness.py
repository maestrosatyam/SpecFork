import asyncio
import json
from pathlib import Path

from app.llm import NebiusClient
from evals.run_eval import eval_item, summarize
from tests.fake_llm import make_transport


async def test_eval_harness_smoke():
    items = json.loads(Path("evals/benchmark/specs.json").read_text())
    item = next(i for i in items if i["id"] == "bill_split")
    client = NebiusClient(api_key="t", transport=make_transport())
    res = await eval_item(item, client, 4, asyncio.Semaphore(1))
    await client.aclose()
    for cond in ("B0", "B1", "SF"):
        assert "alignment" in res["conditions"][cond], res["conditions"][cond]
    assert res["conditions"]["SF"]["questions"] >= 1
    md = summarize([res], 4)
    assert "SpecFork" in md
