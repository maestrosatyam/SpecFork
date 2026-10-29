import ast
import json
import subprocess
import sys

from app.cluster import agreement, cluster_impls, find_axes, surviving_clusters
from app.llm import NebiusClient
from app.pipeline import SpecFork, fuzz_inputs, new_run, validate_inputs, validate_signature
from tests.fake_llm import FRAME, make_transport

SPEC = "Split a restaurant bill evenly among n people. Return how much each person pays, rounded to cents."


def _engine(counter=None):
    client = NebiusClient(api_key="test", transport=make_transport(counter))
    return SpecFork(client, lambda run: None), client


async def test_full_pipeline_offline(tmp_path):
    counter = {}
    eng, client = _engine(counter)
    run = new_run("t1", SPEC, 8)
    await eng.run_all(run)
    assert run["status"] == "awaiting_answers", run.get("error")
    st = [i["status"] for i in run["implementations"]]
    assert st.count("rejected") == 1  # the `import os` implementation
    rej = next(i for i in run["implementations"] if i["status"] == "rejected")
    assert "os" in rej["reject_reason"]
    behaviours = [c for c in run["clusters"] if c["kind"] == "behavior"]
    assert len(behaviours) == 3
    assert behaviours[0]["size"] == 4  # A is the majority
    amb = [q for q in run["questions"] if q["kind"] == "ambiguity"]
    assert len(amb) >= 1
    q = amb[0]
    assert q["text"].startswith("When the bill")
    # every option is backed by executed witness outputs
    assert all(o["examples"] and o["cluster_ids"] for o in q["options"])
    # trace accounting
    assert run["metrics"]["n_calls"] == len(run["trace"]) >= 10
    assert run["metrics"]["total_cost_usd"] > 0
    assert any(t.get("reasoning_excerpt") for t in run["trace"])

    # answer: pick the option containing cluster A
    a_id = behaviours[0]["id"]
    answers = {}
    for qq in amb:
        answers[qq["id"]] = next(o["id"] for o in qq["options"] if a_id in o["cluster_ids"])
    await eng.resolve(run, answers)
    res = run["resolution"]
    assert run["status"] == "resolved"
    assert res["surviving_cluster_ids"] == [a_id]
    assert res["agreement_before_counts"] == [4, 7]
    assert "first people" in res["clarified_spec"]
    ast.parse(res["tests_code"])

    # the generated pytest file passes against the chosen implementation and fails against another
    (tmp_path / "solution.py").write_text(res["reference_code"])
    (tmp_path / "test_locked.py").write_text(res["tests_code"])
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    other = next(i for i in run["implementations"] if i.get("cluster_id") == behaviours[1]["id"])
    (tmp_path / "solution.py").write_text(other["code"])
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode != 0

    await eng.converge(run, 6)
    conv = res["convergence"]
    assert conv["status"] == "done" and conv["agreement_after"] == 1.0 and conv["passed"] == 6
    await client.aclose()


async def test_resolve_requires_answers():
    eng, client = _engine()
    run = new_run("t2", SPEC, 8)
    await eng.run_all(run)
    try:
        await eng.resolve(run, {})
        raise AssertionError("expected failure")
    except Exception as e:  # PipelineError
        assert "not answered" in str(e)
    assert run["status"] == "awaiting_answers"
    await client.aclose()


def test_validate_signature_rejects_injection():
    bad = dict(FRAME, name="split_bill(); import os")
    try:
        validate_signature(bad)
        raise AssertionError
    except Exception as e:
        assert "bad function name" in str(e)


def test_validate_inputs_filters():
    sig = validate_signature(FRAME)
    raw = [{"args": {"total": 1, "n": 2}}, {"args": {"total": 1}}, {"args": {"total": 1, "n": 2}},
           {"args": {"total": 1, "n": 2, "x": 3}}, "junk", {"args": {"total": "x" * 1000, "n": 1}}]
    out = validate_inputs(raw, sig, "model")
    assert [o["args"] for o in out] == [{"total": 1, "n": 2}]


def test_fuzz_deterministic():
    sig = validate_signature(FRAME)
    assert fuzz_inputs(sig, "abc") == fuzz_inputs(sig, "abc")
    assert len(fuzz_inputs(sig, "abc")) == 6


def test_cluster_and_axes_logic():
    o = lambda v: {"ok": True, "value_repr": v}  # noqa: E731
    err = {"ok": False, "value_repr": "raises", "error_type": "ValueError"}
    outcomes = {
        "m0": {"i0": o("1"), "i1": o("a")},
        "m1": {"i0": o("1"), "i1": o("a")},
        "m2": {"i0": o("2"), "i1": o("a")},
        "m3": {"i0": o("1"), "i1": o("b")},
        "m4": {"i0": err, "i1": err},
    }
    cr = cluster_impls(outcomes, ["i0", "i1"])
    assert [c["size"] for c in cr.clusters] == [2, 1, 1, 1]
    assert cr.clusters[-1]["kind"] == "crash"
    rep = {c["id"]: outcomes[c["representative_impl_id"]] for c in cr.clusters}
    axes = find_axes(cr.clusters, rep, ["i0", "i1"])
    assert len(axes) == 2 and all(a.witness_input_ids for a in axes)
    surv, exact = surviving_clusters(cr.clusters, [{"c0", "c1"}, {"c0"}])
    assert surv == ["c0"] and exact
    surv, exact = surviving_clusters(cr.clusters, [{"c1"}, {"c2"}])
    assert not exact and set(surv) == {"c1", "c2"}
    assert agreement(outcomes, {"i0": "1"}) == (3, 5)
    json.dumps(cr.clusters)
