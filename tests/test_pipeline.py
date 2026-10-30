import ast
import json
import subprocess
import sys

from specfork.cluster import agreement, cluster_impls, find_axes, surviving_clusters
from specfork.pipeline import SpecFork, fuzz_inputs, new_run, validate_inputs, validate_signature
from tests.fake_llm import FRAME, make_router, make_transport

SPEC = "Split a restaurant bill evenly among n people. Return how much each person pays, rounded to cents."


def _engine(counter=None):
    client = make_router(make_transport(counter))
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
    for qq in run["questions"]:
        if qq["kind"] == "assumption":
            answers[qq["id"]] = qq["options"][0]["id"]  # keep the consensus behaviour
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


async def test_silent_assumption_override_unlocks_cases():
    eng, client = _engine()
    run = new_run("t3", SPEC, 8)
    await eng.run_all(run)
    a = next(q for q in run["questions"] if q["kind"] == "assumption")
    assert a["affected_input_ids"] == ["i3"]  # unknown ids dropped
    keep, alt = a["options"]
    assert keep["cluster_ids"] and alt["is_alternative"] and alt["cluster_ids"] == []
    behaviours = [c for c in run["clusters"] if c["kind"] == "behavior"]
    answers = {q["id"]: next(o["id"] for o in q["options"] if behaviours[0]["id"] in o["cluster_ids"])
               for q in run["questions"] if q["kind"] == "ambiguity"}
    for q in run["questions"]:
        if q["kind"] == "assumption":
            answers[q["id"]] = q["options"][0]["id"]
    answers[a["id"]] = alt["id"]
    await eng.resolve(run, answers)
    res = run["resolution"]
    assert res["unlocked_input_ids"] == ["i3"]
    assert all(c["input_id"] != "i3" for c in res["locked_cases"])
    await client.aclose()


def test_compatible_options_with_alternative():
    from specfork.cluster import compatible_option_ids
    clusters = [{"id": "c0", "kind": "behavior"}, {"id": "c1", "kind": "behavior"}]
    qs = [{"id": "q0", "options": [{"id": "x", "cluster_ids": ["c0"]}, {"id": "y", "cluster_ids": ["c1"]}]},
          {"id": "q1", "options": [{"id": "z", "cluster_ids": ["c1"]}, {"id": "w", "cluster_ids": [], "is_alternative": True}]}]
    assert compatible_option_ids(qs, {"q0": "x"}, "q1", clusters) == ["w"]
    assert compatible_option_ids(qs, {"q1": "w"}, "q0", clusters) == ["x", "y"]


async def test_free_text_other_answer_is_implemented_and_executed():
    eng, client = _engine()
    run = new_run("t4", SPEC, 8)
    await eng.run_all(run)
    q = next(q for q in run["questions"] if q["kind"] == "ambiguity")
    answers = {x["id"]: x["options"][0]["id"] for x in run["questions"] if x["kind"] in ("ambiguity", "assumption") and x["id"] != q["id"]}
    await eng.resolve(run, answers, {q["id"]: "the first people pay the leftover cents"})
    res = run["resolution"]
    assert run["status"] == "resolved" and res["custom_impl_id"]
    custom = next(o for o in q["options"] if o.get("is_custom"))
    assert q["answer_option_id"] == custom["id"] and custom["examples"]  # executed outputs back the custom answer
    impl = next(i for i in run["implementations"] if i["id"] == res["custom_impl_id"])
    assert impl["status"] == "executed" and impl["model"] == run["settings"]["deep_model"]
    assert all(c["input_id"] in impl["outcomes"] for c in res["locked_cases"])
    await client.aclose()


async def test_assumption_confidence_threshold_and_toggle():
    client = make_router()
    eng = SpecFork(client, lambda run: None, assumption_min_confidence=0.6, max_assumptions=2, assumption_requires_witness=True)
    run = new_run("t5", SPEC, 8)
    await eng.run_all(run)
    assert [q["text"] for q in run["questions"] if q["kind"] == "assumption"] == ["Should a $0 bill be split at all?"]
    off = new_run("t6", SPEC, 8, assumptions=False)
    await eng.run_all(off)
    assert not any(q["kind"] == "assumption" for q in off["questions"])
    await client.aclose()


async def test_mixed_model_fanout_assigns_implementers():
    eng, client = _engine()
    run = new_run("t7", SPEC, 6, implementers=["nvidia/Nemotron-3_5-Lightning", "nvidia/Nemotron-3-Ultra-550b-a55b"])
    await eng.run_all(run)
    models = [i["model"] for i in run["implementations"]]
    assert models.count("nvidia/Nemotron-3-Ultra-550b-a55b") == 3
    await client.aclose()


def test_render_tests_module_option():
    from specfork.pipeline import render_tests

    sig = validate_signature(FRAME)
    code = render_tests(sig, [{"input_id": "i0", "args": {"total": 1, "n": 1}, "expected_repr": "[1]"}], "spec", module="billing.split")
    assert "from billing.split import split_bill" in code


async def test_profile_prompt_override(tmp_path):
    import httpx

    from specfork.llm import ModelRouter
    from specfork.registry import Registry

    f = tmp_path / "specfork.toml"
    f.write_text('[models.lightning]\nprompts = { implement = "You are a senior Python developer. OVERRIDE." }\n')
    seen = []
    base = make_transport()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content.decode())
        return base.handle_request(request)

    router = ModelRouter(Registry.load(f), {"NEBIUS_API_KEY": "t"}, transport=httpx.MockTransport(handler))
    eng = SpecFork(router, lambda run: None)
    run = new_run("t8", SPEC, 4)
    await eng.run_all(run)
    assert any("OVERRIDE" in s for s in seen)
    await router.aclose()


async def test_exception_types_option_locks_exception_class(tmp_path):
    import subprocess
    import sys

    eng, client = _engine()
    run = new_run("t9", SPEC, 8, exception_types=True)
    await eng.run_all(run)
    reprs = {o["value_repr"] for i in run["implementations"] if i.get("outcomes") for o in i["outcomes"].values() if not o["ok"]}
    assert reprs and all(r.startswith("raises:") for r in reprs)
    answers = {q["id"]: q["options"][0]["id"] for q in run["questions"] if q["kind"] in ("ambiguity", "assumption")}
    await eng.resolve(run, answers)
    res = run["resolution"]
    assert any(c["expected_repr"].startswith("raises:") for c in res["locked_cases"])
    (tmp_path / "solution.py").write_text(res["reference_code"])
    (tmp_path / "test_locked.py").write_text(res["tests_code"])
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)], capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    await client.aclose()


async def test_adaptive_n_stops_early_when_behaviours_stabilise():
    eng, client = _engine()
    run = new_run("t10", SPEC, 40, adaptive_n=True)
    await eng.run_all(run)
    assert run["status"] == "awaiting_answers"
    assert 16 <= len(run["implementations"]) < 40  # the scripted fake has only 3 behaviours
    assert any("stopping early" in entry["msg"] for entry in run["log"])
    await client.aclose()
