import inspect
import re
from pathlib import Path

import pytest

from app import canon as canon_mod
from app.sandbox import check_code, run_function

GOOD = '''
import math
def split_bill(total, n):
    if n <= 0:
        raise ValueError("n must be positive")
    cents = round(total * 100)
    base, extra = divmod(cents, n)
    return [(base + (1 if i < extra else 0)) / 100 for i in range(n)]
'''


def test_canon_in_harness_matches_module():
    harness = Path("app/_harness.py").read_text()
    h = re.search(r"def canon\(v, _depth=0\):.*?\n\n\n", harness, re.S).group(0)
    m = inspect.getsource(canon_mod.canon)
    norm = lambda s: re.sub(r"\s+|#.*", "", s.replace("(str, bytes)", "str").replace("_math", "math"))  # noqa: E731
    # both must handle the same type branches
    for token in ["isinstance(v, bool)", "round(f, 9)", "isoformat", "sorted(", "timedelta"]:
        assert token in h and token in m


def test_canon_normalisation():
    c = canon_mod.canon
    assert c(3.0) == c(3) == "3"
    assert c((1, 2)) == c([1, 2])
    assert c(0.1 + 0.2) == c(0.3)
    assert c(33.33) != c(33.34)
    assert c({"b": 1, "a": 2}) == "{'a': 2, 'b': 1}"
    assert c(float("nan")) == "nan"


@pytest.mark.parametrize("code,reason", [
    ("import os\ndef f(x): return x", "import of 'os'"),
    ("def f(x): return open('/etc/passwd').read()", "name 'open'"),
    ("def f(x): return x.__class__.__mro__", "dunder attribute"),
    ("def f(x): return getattr(x, 'y')", "name 'getattr'"),
    ("def f(x): return eval('1')", "name 'eval'"),
    ("import subprocess\ndef f(x): return 1", "import of 'subprocess'"),
    ("from . import x\ndef f(x): return 1", "import of"),
    ("print('hi')\ndef f(x): return 1", "top-level statement"),
    ("def g(x): return 1", "function 'f' not defined"),
    ("def f(x) return 1", "syntax error"),
    ("def f(x): return '{0.__class__}'.format(x)", "suspicious dunder"),
])
def test_static_rejections(code, reason):
    r = check_code(code, "f")
    assert not r.ok and reason in r.reason


def test_static_accepts_good():
    assert check_code(GOOD, "split_bill").ok


async def test_run_function_outcomes():
    res = await run_function(GOOD, "split_bill", [
        {"id": "a", "args": {"total": 100, "n": 3}},
        {"id": "b", "args": {"total": 10, "n": 0}},
    ])
    assert res.ok
    assert res.outcomes["a"] == {"ok": True, "value_repr": "[33.34, 33.33, 33.33]"}
    assert res.outcomes["b"]["ok"] is False and res.outcomes["b"]["error_type"] == "ValueError"


async def test_timeout_and_memory_are_contained():
    code = "def f(x):\n    while True:\n        pass\n"
    res = await run_function(code, "f", [{"id": "a", "args": {"x": 1}}, {"id": "b", "args": {"x": 2}}], per_call_timeout_s=0.3)
    assert res.ok and res.outcomes["a"]["error_type"] == "Timeout" and res.outcomes["b"]["error_type"] == "Timeout"
    code = "def f(x):\n    return len('x' * (10**10))\n"
    res = await run_function(code, "f", [{"id": "a", "args": {"x": 1}}])
    assert res.ok and res.outcomes["a"]["error_type"] == "MemoryError"


async def test_runtime_escape_attempts_blocked():
    # even if the static check were bypassed, the child has no env secrets, no open(), blocked imports
    code = (
        "def f(x):\n"
        "    import importlib\n"
        "    return 1\n"
    )
    res = await run_function(code, "f", [{"id": "a", "args": {"x": 1}}])
    assert res.outcomes["a"]["error_type"] == "ImportError"
    code = "def f(x):\n    return open('/etc/hostname').read()\n"
    res = await run_function(code, "f", [{"id": "a", "args": {"x": 1}}])
    assert res.outcomes["a"]["error_type"] == "NameError"


async def test_child_env_has_no_secrets(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "super-secret")
    code = "import os\ndef f(x):\n    return os.environ.get('NEBIUS_API_KEY')\n"
    # bypass the static check deliberately: the harness importer must still block os
    res = await run_function(code, "f", [{"id": "a", "args": {"x": 1}}])
    assert not res.ok and "blocked" in (res.error or "")


async def test_args_are_copied_between_calls():
    code = "def f(xs):\n    xs.append(1)\n    return len(xs)\n"
    res = await run_function(code, "f", [{"id": "a", "args": {"xs": []}}, {"id": "b", "args": {"xs": []}}])
    assert res.outcomes["a"]["value_repr"] == res.outcomes["b"]["value_repr"] == "1"
