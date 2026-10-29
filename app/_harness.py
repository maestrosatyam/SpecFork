"""Child-process harness. Runs with ``python -I -S`` and an empty environment.

Reads {"code", "func", "inputs", "timeout", "allowed_imports"} JSON on stdin and writes
{"ok", "outcomes": {input_id: {ok, value_repr, error_type?, error_msg?}}} JSON to stdout.
This file must not import anything from the ``app`` package.
"""
import builtins
import json
import signal
import sys

try:
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (15, 16))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
except Exception:  # pragma: no cover - non-POSIX
    pass

sys.setrecursionlimit(2000)

# canonicalisation (kept in sync with app/canon.py; imported lazily before builtins are restricted)
import datetime as _dt  # noqa: E402
import decimal as _decimal  # noqa: E402
import fractions as _fractions  # noqa: E402
import math as _math  # noqa: E402


def canon(v, _depth=0):
    if _depth > 20:
        return "<deep>"
    if v is None:
        return "None"
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (float, _decimal.Decimal, _fractions.Fraction)):
        try:
            f = float(v)
        except (OverflowError, ValueError):
            return str(v)
        if _math.isnan(f):
            return "nan"
        if _math.isinf(f):
            return "inf" if f > 0 else "-inf"
        r = round(f, 9)
        if r == int(r) and abs(r) < 1e15:
            return str(int(r))
        return repr(r)
    if isinstance(v, (str, bytes)):
        return repr(v)
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, _dt.timedelta):
        return "timedelta(%r)" % v.total_seconds()
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(canon(x, _depth + 1) for x in v) + "]"
    if isinstance(v, (set, frozenset)):
        return "{" + ", ".join(sorted(canon(x, _depth + 1) for x in v)) + "}"
    if isinstance(v, dict):
        items = sorted((canon(k, _depth + 1), canon(x, _depth + 1)) for k, x in v.items())
        return "{" + ", ".join(f"{k}: {x}" for k, x in items) + "}"
    try:
        return f"<{type(v).__name__}:{str(v)[:80]}>"
    except Exception:
        return f"<{type(v).__name__}>"


class _Timeout(BaseException):
    pass


def _alarm(signum, frame):
    raise _Timeout()


def main():
    req = json.loads(sys.stdin.read())
    allowed = set(req["allowed_imports"])
    real_import = builtins.__import__

    # pre-import allowed modules while the real importer is available
    for m in allowed:
        try:
            real_import(m)
        except Exception:
            pass

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name.split(".")[0] not in allowed:
            raise ImportError(f"import of {name} blocked")
        return real_import(name, globals, locals, fromlist, level)

    safe_builtins = {
        k: getattr(builtins, k)
        for k in dir(builtins)
        if k not in {"open", "exec", "eval", "compile", "input", "breakpoint", "globals", "locals", "vars",
                     "memoryview", "help", "exit", "quit", "__import__", "getattr", "setattr", "delattr"}
        and not k.startswith("_")
    }
    safe_builtins["__import__"] = safe_import
    safe_builtins["__build_class__"] = builtins.__build_class__
    safe_builtins["__name__"] = "specfork_impl"
    ns = {"__builtins__": safe_builtins, "__name__": "specfork_impl"}

    signal.signal(signal.SIGALRM, _alarm)
    try:
        signal.setitimer(signal.ITIMER_REAL, 3.0)
        exec(compile(req["code"], "<impl>", "exec"), ns)  # noqa: S102 - sandboxed by design
        signal.setitimer(signal.ITIMER_REAL, 0)
    except BaseException as e:  # noqa: BLE001
        signal.setitimer(signal.ITIMER_REAL, 0)
        sys.stdout.write(json.dumps({"ok": False, "error": f"load failed: {type(e).__name__}: {str(e)[:200]}"}))
        return
    fn = ns.get(req["func"])
    if not callable(fn):
        sys.stdout.write(json.dumps({"ok": False, "error": "function not found"}))
        return

    outcomes = {}
    for item in req["inputs"]:
        args = json.loads(json.dumps(item["args"]))  # fresh copy so mutation can't leak between calls
        try:
            signal.setitimer(signal.ITIMER_REAL, float(req["timeout"]))
            val = fn(**args)
            signal.setitimer(signal.ITIMER_REAL, 0)
            outcomes[item["id"]] = {"ok": True, "value_repr": canon(val)[:2000]}
        except _Timeout:
            outcomes[item["id"]] = {"ok": False, "value_repr": "raises", "error_type": "Timeout", "error_msg": "exceeded time limit"}
        except MemoryError:
            signal.setitimer(signal.ITIMER_REAL, 0)
            outcomes[item["id"]] = {"ok": False, "value_repr": "raises", "error_type": "MemoryError", "error_msg": ""}
        except RecursionError:
            signal.setitimer(signal.ITIMER_REAL, 0)
            outcomes[item["id"]] = {"ok": False, "value_repr": "raises", "error_type": "RecursionError", "error_msg": ""}
        except Exception as e:  # noqa: BLE001
            signal.setitimer(signal.ITIMER_REAL, 0)
            outcomes[item["id"]] = {"ok": False, "value_repr": "raises", "error_type": type(e).__name__, "error_msg": str(e)[:200]}
    sys.stdout.write(json.dumps({"ok": True, "outcomes": outcomes}))


main()
