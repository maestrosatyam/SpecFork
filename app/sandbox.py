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
    for node in ast.walk(tree):
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
            return StaticCheck(False, "suspicious dunder string")
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


@dataclass
class ExecResult:
    ok: bool
    outcomes: dict[str, dict[str, Any]]
    error: str | None = None


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
        "allowed_imports": sorted(ALLOWED_IMPORTS),
    })
    with tempfile.TemporaryDirectory(prefix="specfork-") as tmp:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-S", str(HARNESS),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=tmp, env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "LANG": "C.UTF-8"},
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(payload.encode()), timeout=total_timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecResult(False, {}, "process timeout")
    if len(out) > 4_000_000:
        return ExecResult(False, {}, "output too large")
    try:
        data = json.loads(out.decode() or "{}")
    except json.JSONDecodeError:
        return ExecResult(False, {}, f"harness failure: {err.decode()[-300:]}")
    if not data.get("ok"):
        return ExecResult(False, {}, data.get("error", "unknown"))
    return ExecResult(True, data["outcomes"])


_EXEC_SEM: asyncio.Semaphore | None = None


def exec_semaphore() -> asyncio.Semaphore:
    global _EXEC_SEM
    if _EXEC_SEM is None:
        _EXEC_SEM = asyncio.Semaphore(max(2, min(8, (os.cpu_count() or 2) * 2)))
    return _EXEC_SEM
