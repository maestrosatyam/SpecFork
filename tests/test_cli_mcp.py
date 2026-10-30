import json
import subprocess
import sys
from pathlib import Path

import pytest

from specfork import cli
from specfork.api import Client
from specfork.config import Settings
from tests.fake_llm import make_router

SPEC = "Split a restaurant bill evenly among n people. Return how much each person pays, rounded to cents."


@pytest.fixture
def fake_client(monkeypatch):
    router = make_router()

    def factory(settings=None, router_=None, on_update=None):
        return Client(Settings(db_path=""), router=router)

    monkeypatch.setattr(cli, "Client", lambda settings=None: factory(settings))
    return router


def test_parser_and_version():
    p = cli.build_parser()
    a = p.parse_args(["fork", SPEC, "--auto", "--module", "billing", "--out", "t"])
    assert a.cmd == "fork" and a.module == "billing" and a.auto


def test_load_answers(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"q0": "q0g1", "a0": {"other": "raise for negative totals"}}))
    assert cli.load_answers(str(f)) == ({"q0": "q0g1"}, {"a0": "raise for negative totals"})


async def test_cli_fork_auto_writes_tests(tmp_path, fake_client, capsys):
    a = cli.build_parser().parse_args(["fork", SPEC, "-n", "8", "--auto", "--out", str(tmp_path), "--module", "billing",
                                       "--reference", str(tmp_path / "billing.py"), "--allow-weak-sandbox"])
    assert await cli.cmd_fork(a) == 0
    test_file = tmp_path / "test_split_bill.py"
    assert "from billing import split_bill" in test_file.read_text()
    # the written tests pass against the written reference implementation
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(test_file)],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Clarified spec" in capsys.readouterr().out


async def test_cli_json_two_step(tmp_path, fake_client, capsys):
    a = cli.build_parser().parse_args(["fork", SPEC, "-n", "8", "--json", "--allow-weak-sandbox"])
    assert await cli.cmd_fork(a) == 0
    run = json.loads(capsys.readouterr().out)
    assert run["status"] == "awaiting_answers" and run["questions"]
    (tmp_path / "run.json").write_text(json.dumps(run))
    b = cli.build_parser().parse_args(["resolve", str(tmp_path / "run.json"), "--auto", "--json", "--allow-weak-sandbox"])
    assert await cli.cmd_resolve(b) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "resolved" and out["resolution"]["locked_cases"]


def test_mcp_server_speaks_json_rpc_over_stdio():
    pytest.importorskip("mcp")
    exe = Path(sys.executable).with_name("specfork")
    cmd = [str(exe), "mcp"] if exe.exists() else [sys.executable, "-m", "specfork.cli", "mcp"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        def send(m):
            p.stdin.write(json.dumps(m) + "\n")
            p.stdin.flush()

        def recv():
            while True:
                line = p.stdout.readline()
                if line.strip():
                    return json.loads(line)

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}})
        assert recv()["result"]["serverInfo"]["name"] == "specfork"
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in recv()["result"]["tools"]}
        assert names == {"fork_spec", "list_questions", "answer", "get_tests", "get_clarified_spec", "refork"}
    finally:
        p.terminate()


async def test_ci_forks_then_resolves_committed_answers(tmp_path, fake_client, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "bill.md").write_text(SPEC)
    args = ["ci", "specs/*.md", "-n", "8", "--comment-file", "c.md", "--fail-on-open", "--allow-weak-sandbox"]
    assert await cli.cmd_ci(cli.build_parser().parse_args(args)) == 1  # open questions -> gate fails
    body = (tmp_path / "c.md").read_text()
    assert "has" in body and "`q0`" in body and "→" in body
    run = json.loads((tmp_path / ".specfork" / "bill.run.json").read_text())
    from specfork.types import Run
    answers = cli.auto_answers(Run.model_validate(run))
    (tmp_path / ".specfork" / "bill.answers.json").write_text(json.dumps(answers))
    assert await cli.cmd_ci(cli.build_parser().parse_args(args)) == 0
    assert (tmp_path / "tests" / "specfork" / "test_split_bill.py").exists()
    assert "resolved" in (tmp_path / "c.md").read_text()
