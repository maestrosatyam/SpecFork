import asyncio
import json
from pathlib import Path

from evals.run_eval import eval_item, summarize
from tests.fake_llm import make_router


async def test_eval_harness_smoke():
    items = json.loads(Path("evals/benchmark/specs.json").read_text())
    item = next(i for i in items if i["id"] == "bill_split")
    client = make_router()
    res = await eval_item(item, client, 4, asyncio.Semaphore(1))
    await client.aclose()
    for cond in ("B0", "B1", "SF"):
        assert "alignment" in res["conditions"][cond], res["conditions"][cond]
    assert res["conditions"]["SF"]["questions"] >= 1
    md = summarize([res], 4)
    assert "SpecFork" in md


def test_bootstrap_ci_brackets_mean():
    from evals.run_eval import bootstrap_ci

    lo, hi = bootstrap_ci([0.0, 0.5, 1.0, 1.0, 0.25])
    assert 0.0 <= lo <= 0.55 <= hi <= 1.0
    assert bootstrap_ci([0.3, 0.3]) == (0.3, 0.3)
