import inspect
import re
from pathlib import Path

import pytest

from specfork import canon as canon_mod
from specfork.sandbox import check_code, run_function

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
    harness = Path("specfork/_harness.py").read_text()
    h = re.search(r"def canon\(v, _depth=0\):.*?\n\n\n", harness, re.S).group(0)
    m = inspect.getsource(canon_mod.canon)
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
    ("def f(x): return x.__class__.__mro__", "not allowed"),
    ("def f(x): return getattr(x, 'y')", "name 'getattr'"),
    ("def f(x): return eval('1')", "name 'eval'"),
    ("import subprocess\ndef f(x): return 1", "import of 'subprocess'"),
    ("from . import x\ndef f(x): return 1", "import of"),
    ("print('hi')\ndef f(x): return 1", "top-level statement"),
    ("def g(x): return 1", "function 'f' not defined"),
    ("def f(x) return 1", "syntax error"),
    ("def f(x): return '{0.__class__}'.format(x)", "not allowed"),
    ("def f(x): return '{0.gi_frame}'.format(x)", "not allowed"),
    ("def f(x): return '{0[a]}'.format(x)", "not allowed"),
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


# ---- regression tests for known CPython sandbox-escape gadgets (static layer)
@pytest.mark.parametrize("code", [
    "import random\ndef f(x): return random._os.getcwd()",
    "import typing\ndef f(x): return typing.sys.modules",
    "import dataclasses\ndef f(x): return dataclasses.sys",
    "import operator\ndef f(x): return operator.attrgetter('_' + '_class__')(x)",
    "from operator import attrgetter\ndef f(x): return attrgetter('a')(x)",
    "def f(x):\n    t = '{0._' + '_class__}'\n    return t.format(x)",
    "def f(x):\n    g = (i for i in [1])\n    return g.gi_frame.f_globals",
    "def f(x): return type(x).mro()",
    "import string\ndef f(x): return string.Formatter().format('{0}', x)",
    "def f(x):\n    try:\n        1/0\n    except Exception as e:\n        return e.__traceback__.tb_frame",
    "from random import _os\ndef f(x): return _os",
])
def test_escape_gadgets_rejected_statically(code):
    assert not check_code(code, "f").ok


# ---- runtime layer: even if code got past the static check, the module proxies hide internals
async def test_runtime_module_proxies_hide_internals():
    for code in [
        "import random\ndef f(x):\n    return hasattr(random, '_os') or hasattr(random, 'os')\n",
        "import typing\ndef f(x):\n    return hasattr(typing, 'sys')\n",
        "import operator\ndef f(x):\n    return hasattr(operator, 'attrgetter')\n",
        "import string\ndef f(x):\n    return hasattr(string, 'Formatter')\n",
    ]:
        res = await run_function(code, "f", [{"id": "a", "args": {"x": 1}}])
        assert res.ok and res.outcomes["a"]["value_repr"] == "False", (code, res)


async def test_legit_stdlib_usage_still_works():
    code = (
        "import math, statistics, datetime, re\n"
        "from collections import Counter\n"
        "from decimal import Decimal, ROUND_HALF_UP\n"
        "def f(x):\n"
        "    d = datetime.date.fromisoformat('2024-02-29') + datetime.timedelta(days=1)\n"
        "    q = Decimal('2.675').quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)\n"
        "    return [math.floor(2.5), statistics.median([1, 2, 3, 4]), d.isoformat(), float(q),\n"
        "            Counter('aab').most_common(1)[0][0], re.sub(r'\\s+', ' ', 'a  b'), '{:.2f}'.format(1/3)]\n"
    )
    assert check_code(code, "f").ok
    res = await run_function(code, "f", [{"id": "a", "args": {"x": 1}}])
    assert res.outcomes["a"] == {"ok": True, "value_repr": "[2, 2.5, '2024-03-01', 2.68, 'a', 'a b', '0.33']"}


# ---- regressions from the 2026-10-30 independent security review
@pytest.mark.parametrize("code", [
    # match-class keyword patterns name attributes as plain strings
    "from collections import namedtuple\ndef f(x):\n    match namedtuple:\n        case object(__globals__=g):\n            return g\n",
    "def f(x):\n    match x:\n        case {'a': 1}:\n            return 1\n    return 0\n",
    # unbound str.format reference
    "def f(x):\n    fm = str.format\n    return fm('{0}', x)\n",
    # dunder keyword argument names
    "def f(x):\n    return dict(__globals__=1)\n",
])
def test_review_gadgets_rejected(code):
    assert not check_code(code, "f").ok


async def test_unbounded_output_is_capped():
    # passes the static check; prints far more than the cap
    code = "def f(x):\n    s = 'x' * 1000000\n    for i in range(300):\n        print(s)\n    return 1\n"
    assert check_code(code, "f").ok
    res = await run_function(code, "f", [{"id": "a", "args": {"x": 1}}])
    assert not res.ok and res.error == "output too large"


async def test_no_process_creation_in_child():
    # simulate code that got past the static layer: the harness itself must forbid new processes
    import json as _json
    import subprocess as _sp
    import sys as _sys
    payload = {"code": "import os\ndef f(x):\n    return os.fork()\n", "func": "f", "inputs": [{"id": "a", "args": {"x": 1}}],
               "timeout": 1, "allowed_imports": ["os"]}
    out = _sp.run([_sys.executable, "-I", "-S", "specfork/_harness.py"], input=_json.dumps(payload).encode(),
                  capture_output=True, env={"PATH": "/usr/bin:/bin"}, timeout=20).stdout
    res = _json.loads(out)
    assert res["outcomes"]["a"]["ok"] is False  # BlockingIOError / PermissionError from RLIMIT_NPROC
