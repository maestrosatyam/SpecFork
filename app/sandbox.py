"""Static safety check + isolated execution of model-written Python functions.

Defence in depth for untrusted code (the spec text is user input and the code is model output,
so both may be adversarial / prompt-injected):

1. Static AST allow-list (``check_code``): only whitelisted stdlib imports, no dunder attribute
   access, no file/process/introspection builtins, no ``global``/``nonlocal`` tricks, size caps.
2. Execution in a separate ``python -I`` subprocess with an empty environment (no API keys),
   a throw-away working directory, POSIX rlimits (CPU, address space, file size, open files),
   restricted builtins, a per-call wall-clock timer and an overall process timeout.
3. Output is size-capped JSON; the parent never ``eval``s anything the child returns.
"""
from __future__ import annotations

import ast
import re
import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALLOWED_IMPORTS = {
    "math", "decimal", "fractions", "datetime", "re", "string", "collections", "itertools",
    "functools", "statistics", "unicodedata", "typing", "calendar", "heapq", "bisect",
    "operator", "textwrap", "dataclasses", "enum", "numbers", "copy", "random", "zoneinfo",
}
BANNED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "locals",
    "vars", "memoryview", "help", "exit", "quit", "getattr", "setattr", "delattr", "__builtins__",
    "__loader__", "__spec__",
}
# attribute names that lead from ordinary objects to frames, code objects, globals or modules
BANNED_ATTRS = {
    "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "ag_frame", "ag_code", "f_globals", "f_locals",
    "f_builtins", "f_back", "f_code", "tb_frame", "tb_next", "func_globals", "mro", "format_map",
    "attrgetter", "methodcaller", "Formatter", "sys", "os", "builtins", "modules", "subprocess", "importlib",
    "posix", "io", "socket", "shutil", "ctypes", "inspect", "types", "gc", "system", "popen", "spawn",
    "load_module", "exec_module", "get_data",
}
MAX_CODE_CHARS = 12_000
HARNESS = Path(__file__).with_name("_harness.py")
# When set, the harness refuses to run model code unless it could drop network access (user+net namespace).
REQUIRE_ISOLATION = os.environ.get("SANDBOX_REQUIRE_ISOLATION", "0") == "1"


@dataclass
class StaticCheck:
    ok: bool
    reason: str | None = None


def check_code(code: str, func_name: str) -> StaticCheck:
    if len(code) > MAX_CODE_CHARS:
        return StaticCheck(False, "code too long")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return StaticCheck(False, f"syntax error: {e.msg} (line {e.lineno})")
    found = False
    # `.format` is only allowed as a direct call on a string literal with simple fields ("{:.2f}", "{0}", "{name}").
    safe_format_attrs = {id(n.func) for n in ast.walk(tree)
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "format"
                         and isinstance(n.func.value, ast.Constant) and isinstance(n.func.value.value, str)
                         and _simple_format_fields(n.func.value.value)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("format", "format_map") and id(node) not in safe_format_attrs:
            return StaticCheck(False, "str.format not allowed except on literal templates with simple fields")
        if isinstance(node, (ast.Match, ast.MatchClass, ast.MatchMapping, ast.MatchAs, ast.MatchStar)):
            return StaticCheck(False, "match statements are not allowed")
        # Catch-all: every identifier stored anywhere in the tree (attribute names, keyword-argument names,
        # import aliases, parameter names...) must be neither private/dunder nor a known escape gadget.
        for field, value in ast.iter_fields(node):
            if isinstance(node, ast.Constant) or field in ("type_comment", "kind", "tag"):
                continue
            names = [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)] if isinstance(value, list) else []
            for ident in names:
                if ident.startswith("__") and ident != "__name__":
                    return StaticCheck(False, f"dunder identifier '{ident}' not allowed")
                if field in ("attr", "arg", "kwd_attrs") and (ident.startswith("_") or ident in BANNED_ATTRS):
                    return StaticCheck(False, f"identifier '{ident}' not allowed")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                if m.split(".")[0] not in ALLOWED_IMPORTS:
                    return StaticCheck(False, f"import of '{m}' is not allowed")
            if isinstance(node, ast.ImportFrom) and node.level:
                return StaticCheck(False, "relative import not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return StaticCheck(False, f"private/dunder attribute '{node.attr}' not allowed")
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_ATTRS:
            return StaticCheck(False, f"attribute '{node.attr}' not allowed")
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"
              and not (isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str))):
            return StaticCheck(False, "str.format on a non-literal template is not allowed")
        elif isinstance(node, ast.Name) and (node.id in BANNED_NAMES or node.id.startswith("__")):
            if not (node.id == "__name__" and isinstance(node.ctx, ast.Load)):
                return StaticCheck(False, f"name '{node.id}' not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            return StaticCheck(False, "global/nonlocal not allowed")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)):
            return StaticCheck(False, "async code not allowed")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            return StaticCheck(False, "dunder strings not allowed")
        elif isinstance(node, ast.alias) and (node.name.startswith("_") or node.name in BANNED_ATTRS):
            return StaticCheck(False, f"import of name '{node.name}' not allowed")
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            found = True
    # top level may only contain imports, defs, simple constant assignments and docstrings
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        return StaticCheck(False, f"top-level statement '{type(node).__name__}' not allowed")
    if not found:
        return StaticCheck(False, f"function '{func_name}' not defined")
    return StaticCheck(True)


def _simple_format_fields(template: str) -> bool:
    """True when every replacement field is a bare position/name (no attribute or index lookups)."""
    import string

    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError:
        return False
    for _, field, spec, _ in parsed:
        if field and ("." in field or "[" in field):
            return False
        # nested fields inside a format spec ("{:>{w}}") are looked up too: they must be bare as well
        for nested in re.findall(r"\{([^{}]*)\}", spec or ""):
            if "." in nested or "[" in nested:
                return False
    return True


@dataclass
class ExecResult:
    ok: bool
    outcomes: dict[str, dict[str, Any]]
    error: str | None = None
    net_isolated: bool | None = None


async def run_function(
    code: str,
    func_name: str,
    inputs: list[dict[str, Any]],
    per_call_timeout_s: float = 1.0,
    total_timeout_s: float = 20.0,
) -> ExecResult:
    """Run ``func_name`` from ``code`` on each input ({"id", "args"}) in an isolated subprocess."""
    payload = json.dumps({
        "code": code, "func": func_name, "inputs": inputs, "timeout": per_call_timeout_s,
        "allowed_imports": sorted(ALLOWED_IMPORTS), "require_isolation": REQUIRE_ISOLATION,
    })
    with tempfile.TemporaryDirectory(prefix="specfork-") as tmp:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-S", str(HARNESS),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=tmp, env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "LANG": "C.UTF-8"},
            start_new_session=True,  # own process group, so everything it spawns can be killed together
        )
        try:
            out = await asyncio.wait_for(_bounded_exchange(proc, payload.encode()), timeout=total_timeout_s)
        except asyncio.TimeoutError:
            return ExecResult(False, {}, "process timeout")
        except OutputTooLarge:
            return ExecResult(False, {}, "output too large")
        finally:
            _kill_group(proc)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
    try:
        data = json.loads(out.decode() or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        return ExecResult(False, {}, "harness returned invalid output")
    if not isinstance(data, dict) or not data.get("ok") or not isinstance(data.get("outcomes"), dict):
        err = data.get("error", "unknown") if isinstance(data, dict) else "unknown"
        return ExecResult(False, {}, str(err)[:200])
    return ExecResult(True, data["outcomes"], net_isolated=bool(data.get("net_isolated")))


async def selftest() -> dict[str, Any]:
    """Run a trivial function through the full sandbox and report the isolation actually in effect."""
    res = await run_function("def f(x):\n    return x + 1\n", "f", [{"id": "a", "args": {"x": 1}}])
    return {"ok": res.ok and res.outcomes.get("a", {}).get("value_repr") == "2", "net_isolated": res.net_isolated,
            "require_isolation": REQUIRE_ISOLATION, "error": res.error}


MAX_OUTPUT_BYTES = 4_000_000


class OutputTooLarge(Exception):
    pass


async def _bounded_exchange(proc: asyncio.subprocess.Process, payload: bytes) -> bytes:
    """Send the payload, then read stdout with a hard cap (never buffer unbounded child output)."""
    assert proc.stdin is not None and proc.stdout is not None
    try:
        proc.stdin.write(payload)
        await proc.stdin.drain()
        proc.stdin.close()
    except (BrokenPipeError, ConnectionResetError):
        pass
    chunks, total = [], 0
    while True:
        chunk = await proc.stdout.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_OUTPUT_BYTES:
            raise OutputTooLarge()
        chunks.append(chunk)
    return b"".join(chunks)


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    import signal

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


_EXEC_SEM: asyncio.Semaphore | None = None


def exec_semaphore() -> asyncio.Semaphore:
    global _EXEC_SEM
    if _EXEC_SEM is None:
        _EXEC_SEM = asyncio.Semaphore(int(os.environ.get("SANDBOX_CONCURRENCY", "0")) or max(2, min(8, (os.cpu_count() or 2) * 2)))
    return _EXEC_SEM
