"""Canonical, comparable string forms of Python values.

Two implementations "behave the same" on an input when the canonical forms of their
results are equal. Canonicalisation deliberately ignores representation noise that
users don't care about (tuple vs list, 3 vs 3.0, float round-off below 1e-9) while
keeping every user-visible difference (33.33 vs 33.34, "a" vs "A", order of lists).

This module is also embedded verbatim in generated pytest files, so it must stay
standard-library-only and self-contained.
"""
from __future__ import annotations

import datetime as _dt
import decimal as _decimal
import fractions as _fractions
import math as _math

RAISES = "raises"


def canon(v, _depth=0):  # noqa: C901 - flat type dispatch is clearer here
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
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, bytes):
        return repr(v)
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, _dt.timedelta):
        return f"timedelta({v.total_seconds()!r})"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(canon(x, _depth + 1) for x in v) + "]"
    if isinstance(v, (set, frozenset)):
        return "{" + ", ".join(sorted(canon(x, _depth + 1) for x in v)) + "}"
    if isinstance(v, dict):
        items = sorted((canon(k, _depth + 1), canon(x, _depth + 1)) for k, x in v.items())
        return "{" + ", ".join(f"{k}: {x}" for k, x in items) + "}"
    try:
        return f"<{type(v).__name__}:{str(v)[:80]}>"
    except Exception:  # noqa: BLE001
        return f"<{type(v).__name__}>"
