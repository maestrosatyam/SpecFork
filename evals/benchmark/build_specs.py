"""Source of truth for the SpecFork benchmark.

Items are authored here as Python literals (so reference code can be written
as readable multi-line strings) and dumped to ``specs.json``:

    .venv/bin/python evals/benchmark/build_specs.py
    .venv/bin/python evals/benchmark/validate.py

Hand-written for the Nebius x NVIDIA hackathon, 2026-10-29. No LLM output.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent


def code(s: str) -> str:
    return textwrap.dedent(s).strip("\n") + "\n"


def P(name: str, type_: str, description: str) -> dict:
    return {"name": name, "type": type_, "description": description}


def sig(name: str, params: list[dict], ret_type: str, ret_desc: str) -> dict:
    return {"name": name, "params": params, "returns": {"type": ret_type, "description": ret_desc}}


def axis(id_: str, description: str, intended: str, others: list[str], alts: list[tuple[str, str]]) -> dict:
    return {
        "id": id_,
        "description": description,
        "intended": intended,
        "interpretations": [intended, *others],
        "alt_references": [{"interpretation": i, "code": code(c)} for i, c in alts],
    }


ITEMS: list[dict] = []


def item(**kw) -> None:
    kw["reference"] = code(kw["reference"])
    kw.setdefault("axes", [])
    order = ["id", "category", "ambiguous", "spec", "signature", "axes", "intent", "reference", "test_inputs"]
    ITEMS.append({k: kw[k] for k in order})


# ---------------------------------------------------------------------------
# Ambiguous items
# ---------------------------------------------------------------------------

item(
    id="bill_split",
    category="money",
    ambiguous=True,
    spec="Split a restaurant bill evenly between n people and return how much each person pays, in dollars rounded to the cent.",
    signature=sig("split_bill", [P("total", "float", "bill total in dollars"), P("n", "int", "number of people")],
                  "list[float]", "amount each person pays, one entry per person"),
    axes=[axis(
        "leftover_cents",
        "What happens to cents that don't divide evenly (e.g. $100 / 3).",
        "shares sum exactly to the total; the leftover cents go one each to the first people in the list",
        ["shares sum exactly to the total; the leftover cents go to the last person/people",
         "everyone pays round(total / n, 2), even if the shares don't add up to the total"],
        [("shares sum exactly to the total; the leftover cents go to the last person/people", """
            def split_bill(total: float, n: int) -> list[float]:
                if n <= 0:
                    raise ValueError("n must be positive")
                cents = round(total * 100)
                if cents < 0:
                    raise ValueError("total must be non-negative")
                base, extra = divmod(cents, n)
                return [(base + (1 if i >= n - extra else 0)) / 100 for i in range(n)]
         """),
         ("everyone pays round(total / n, 2), even if the shares don't add up to the total", """
            def split_bill(total: float, n: int) -> list[float]:
                if n <= 0:
                    raise ValueError("n must be positive")
                if round(total * 100) < 0:
                    raise ValueError("total must be non-negative")
                return [round(total / n, 2)] * n
         """)],
    )],
    intent=("The shares must add up exactly to the total (to the cent). Work in whole cents: everyone gets "
            "floor(cents / n) and the leftover cents are handed out one each to the first people in the list, "
            "so $100 between 3 is [33.34, 33.33, 33.33]. n <= 0 raises ValueError; a negative total raises ValueError; "
            "a $0 bill gives everyone 0.0."),
    reference="""
        def split_bill(total: float, n: int) -> list[float]:
            if n <= 0:
                raise ValueError("n must be positive")
            cents = round(total * 100)
            if cents < 0:
                raise ValueError("total must be non-negative")
            base, extra = divmod(cents, n)
            return [(base + (1 if i < extra else 0)) / 100 for i in range(n)]
    """,
    test_inputs=[
        {"total": 100, "n": 3}, {"total": 10, "n": 4}, {"total": 0.05, "n": 3}, {"total": 1, "n": 3},
        {"total": 20, "n": 6}, {"total": 7, "n": 1}, {"total": 100.01, "n": 2}, {"total": 0, "n": 3},
        {"total": 2, "n": 3}, {"total": 59.99, "n": 4}, {"total": 1000, "n": 7}, {"total": 0.01, "n": 2},
        {"total": 10, "n": 0}, {"total": -5, "n": 2},
    ],
)

item(
    id="round_temperature",
    category="numbers",
    ambiguous=True,
    spec="Round a temperature reading in degrees Celsius to the nearest whole degree for the dashboard display.",
    signature=sig("round_temperature", [P("celsius", "float", "temperature reading in degrees Celsius")],
                  "int", "temperature rounded to a whole degree"),
    axes=[
        axis("tie_rule", "How exact .5 readings are rounded (2.5, 3.5, ...).",
             "round half away from zero (2.5 -> 3, 3.5 -> 4)",
             ["round half to even / banker's rounding, Python's round() (2.5 -> 2, 3.5 -> 4)"],
             [("round half to even / banker's rounding, Python's round() (2.5 -> 2, 3.5 -> 4)", """
                def round_temperature(celsius: float) -> int:
                    return int(round(celsius))
              """)]),
        axis("negative_ties", "Which way negative .5 readings go (-2.5).",
             "symmetric: -2.5 -> -3, -0.5 -> -1",
             ["always round .5 up toward +infinity: -2.5 -> -2, -0.5 -> 0 (floor(x + 0.5))"],
             [("always round .5 up toward +infinity: -2.5 -> -2, -0.5 -> 0 (floor(x + 0.5))", """
                import math

                def round_temperature(celsius: float) -> int:
                    return math.floor(celsius + 0.5)
              """)]),
    ],
    intent=("Round like it's taught in school: an exact .5 always rounds away from zero, symmetrically for negatives. "
            "2.5 -> 3, 3.5 -> 4, -2.5 -> -3, -0.5 -> -1, 21.4 -> 21, -3.6 -> -4. Treat the value as the decimal number "
            "that was written (use its repr), and return an int."),
    reference="""
        from decimal import Decimal, ROUND_HALF_UP

        def round_temperature(celsius: float) -> int:
            return int(Decimal(repr(celsius)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    """,
    test_inputs=[{"celsius": v} for v in
                 [2.5, 3.5, 0.5, 1.5, -2.5, -0.5, -1.5, 21.4, 21.6, -3.6, -3.4, 0.0, 18.0, 36.6, -12.5]],
)

item(
    id="email_dedupe",
    category="data-cleaning",
    ambiguous=True,
    spec="Remove duplicate email addresses from a newsletter signup list. Addresses that differ only in capitalization count as duplicates.",
    signature=sig("dedupe_emails", [P("emails", "list[str]", "email addresses in signup order")],
                  "list[str]", "the list with duplicates removed"),
    axes=[
        axis("which_kept", "Which occurrence of a duplicate survives (affects both the spelling kept and the output order).",
             "keep the first occurrence, in original signup order",
             ["keep the last occurrence (most recent signup), ordered by where those last occurrences appear"],
             [("keep the last occurrence (most recent signup), ordered by where those last occurrences appear", """
                def dedupe_emails(emails: list[str]) -> list[str]:
                    last = {}
                    for i, e in enumerate(emails):
                        e2 = e.strip()
                        last[e2.lower()] = (i, e2)
                    return [v for _, v in sorted(last.values())]
              """)]),
        axis("output_case", "Whether the surviving address keeps its original capitalization.",
             "keep the address exactly as the user typed it (original capitalization)",
             ["lowercase every address in the output"],
             [("lowercase every address in the output", """
                def dedupe_emails(emails: list[str]) -> list[str]:
                    seen = set()
                    out = []
                    for e in emails:
                        key = e.strip().lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(key)
                    return out
              """)]),
        axis("whitespace", "Whether stray leading/trailing spaces are trimmed before comparing.",
             "trim surrounding whitespace before comparing and in the output",
             ["compare and return the strings as-is (whitespace makes them different)"],
             [("compare and return the strings as-is (whitespace makes them different)", """
                def dedupe_emails(emails: list[str]) -> list[str]:
                    seen = set()
                    out = []
                    for e in emails:
                        key = e.lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(e)
                    return out
              """)]),
    ],
    intent=("Trim surrounding whitespace, compare case-insensitively, and keep the FIRST occurrence of each address "
            "exactly as it was typed (original capitalization), preserving the original signup order. "
            "Do not do any other normalization (no Gmail dot/plus handling)."),
    reference="""
        def dedupe_emails(emails: list[str]) -> list[str]:
            seen = set()
            out = []
            for e in emails:
                e2 = e.strip()
                key = e2.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(e2)
            return out
    """,
    test_inputs=[{"emails": v} for v in [
        ["alice@example.com", "Alice@Example.com"],
        ["bob@x.com", "carol@x.com", "BOB@x.com"],
        [],
        ["solo@x.com"],
        ["a@x.com", "b@x.com", "A@X.COM", "c@x.com", "B@x.com"],
        [" dave@x.com", "dave@x.com "],
        ["Eve@Corp.io", "eve@corp.io", "EVE@CORP.IO"],
        ["x@y.com", "x@y.com"],
        ["Mixed@Case.com"],
        ["zed@a.com", "amy@a.com", "Zed@A.com"],
        ["frank@x.com ", "Grace@x.com", "frank@X.com"],
        ["one@a.com", "two@a.com", "three@a.com"],
    ]],
)

item(
    id="business_days",
    category="dates",
    ambiguous=True,
    spec="Count the number of business days between two dates (given as 'YYYY-MM-DD'). Weekends don't count; ignore public holidays.",
    signature=sig("business_days_between", [P("start", "str", "ISO date"), P("end", "str", "ISO date")],
                  "int", "number of business days"),
    axes=[
        axis("endpoints", "Whether the start and end dates themselves are counted.",
             "inclusive of both start and end (Mon..Fri of one week = 5; same weekday = 1)",
             ["half-open: include start, exclude end (numpy.busday_count style; Mon..Fri = 4)",
              "exclusive of both (only the days strictly between; Mon..Fri = 3)"],
             [("half-open: include start, exclude end (numpy.busday_count style; Mon..Fri = 4)", """
                from datetime import date, timedelta

                def business_days_between(start: str, end: str) -> int:
                    a = date.fromisoformat(start)
                    b = date.fromisoformat(end)
                    if b < a:
                        a, b = b, a
                    count = 0
                    d = a
                    while d < b:
                        if d.weekday() < 5:
                            count += 1
                        d += timedelta(days=1)
                    return count
              """),
              ("exclusive of both (only the days strictly between; Mon..Fri = 3)", """
                from datetime import date, timedelta

                def business_days_between(start: str, end: str) -> int:
                    a = date.fromisoformat(start)
                    b = date.fromisoformat(end)
                    if b < a:
                        a, b = b, a
                    count = 0
                    d = a + timedelta(days=1)
                    while d < b:
                        if d.weekday() < 5:
                            count += 1
                        d += timedelta(days=1)
                    return count
              """)]),
        axis("reversed_order", "What happens when end is before start.",
             "order doesn't matter: swap the dates, result is never negative",
             ["return a negative count", "return 0"],
             [("return a negative count", """
                from datetime import date, timedelta

                def business_days_between(start: str, end: str) -> int:
                    a = date.fromisoformat(start)
                    b = date.fromisoformat(end)
                    sign = 1
                    if b < a:
                        a, b, sign = b, a, -1
                    count = 0
                    d = a
                    while d <= b:
                        if d.weekday() < 5:
                            count += 1
                        d += timedelta(days=1)
                    return sign * count
              """),
              ("return 0", """
                from datetime import date, timedelta

                def business_days_between(start: str, end: str) -> int:
                    a = date.fromisoformat(start)
                    b = date.fromisoformat(end)
                    count = 0
                    d = a
                    while d <= b:
                        if d.weekday() < 5:
                            count += 1
                        d += timedelta(days=1)
                    return count
              """)]),
    ],
    intent=("Count Monday-Friday dates in the range INCLUDING both the start and the end date: Monday to the following "
            "Friday is 5, the same weekday date passed twice is 1, a Saturday-Sunday range is 0. If end is before start, "
            "just swap them; the answer never depends on argument order and is never negative. Holidays are ignored."),
    reference="""
        from datetime import date, timedelta

        def business_days_between(start: str, end: str) -> int:
            a = date.fromisoformat(start)
            b = date.fromisoformat(end)
            if b < a:
                a, b = b, a
            count = 0
            d = a
            while d <= b:
                if d.weekday() < 5:
                    count += 1
                d += timedelta(days=1)
            return count
    """,
    test_inputs=[{"start": s, "end": e} for s, e in [
        ("2025-03-03", "2025-03-07"), ("2025-03-03", "2025-03-03"), ("2025-03-08", "2025-03-09"),
        ("2025-03-07", "2025-03-10"), ("2025-03-01", "2025-03-31"), ("2025-03-10", "2025-03-03"),
        ("2024-12-23", "2025-01-03"), ("2025-01-01", "2025-12-31"), ("2025-03-09", "2025-03-15"),
        ("2025-03-14", "2025-03-03"), ("2025-02-28", "2025-03-03"), ("2024-02-26", "2024-03-01"),
        ("2025-03-05", "2025-03-05"),
    ]],
)

item(
    id="slugify",
    category="text",
    ambiguous=True,
    spec="Turn a blog post title into a URL slug.",
    signature=sig("slugify", [P("title", "str", "the post title")], "str", "URL-safe slug"),
    axes=[
        axis("non_ascii", "What happens to accented / non-ASCII letters such as 'é' or 'ñ'.",
             "transliterate accented letters to plain ASCII (Café -> cafe); drop anything that can't be",
             ["treat non-ASCII characters like punctuation, i.e. as separators (Café -> caf)",
              "keep Unicode letters in the slug (Café -> café)"],
             [("treat non-ASCII characters like punctuation, i.e. as separators (Café -> caf)", """
                import re

                def slugify(title: str) -> str:
                    s = re.sub(r"['’]", "", title).lower()
                    s = re.sub(r"[^a-z0-9]+", "-", s)
                    return s.strip("-")
              """),
              ("keep Unicode letters in the slug (Café -> café)", """
                import re

                def slugify(title: str) -> str:
                    s = re.sub(r"['’]", "", title).lower()
                    s = re.sub(r"[\\W_]+", "-", s)
                    return s.strip("-")
              """)]),
        axis("apostrophes", "Whether an apostrophe splits a word (Don't -> dont vs don-t).",
             "remove apostrophes without a gap (Don't -> dont)",
             ["apostrophes are punctuation like any other and become a hyphen (Don't -> don-t)"],
             [("apostrophes are punctuation like any other and become a hyphen (Don't -> don-t)", """
                import re
                import unicodedata

                def slugify(title: str) -> str:
                    s = unicodedata.normalize("NFKD", title)
                    s = s.replace("’", "'")
                    s = s.encode("ascii", "ignore").decode("ascii").lower()
                    s = re.sub(r"[^a-z0-9]+", "-", s)
                    return s.strip("-")
              """)]),
    ],
    intent=("Lowercase. Accented Latin letters are transliterated to their base ASCII letter (é->e, ñ->n, ü->u, ï->i); any "
            "other non-ASCII character (emoji, symbols) is simply dropped. Apostrophes (straight ' or curly ’) are removed "
            "without leaving a gap, so \"Don't Panic\" -> \"dont-panic\". Every other run of non-alphanumeric characters "
            "(spaces, punctuation, underscores, symbols) becomes a single hyphen. No leading/trailing hyphens. "
            "Empty title -> empty string."),
    reference="""
        import re
        import unicodedata

        def slugify(title: str) -> str:
            s = re.sub(r"['’]", "", title)
            s = unicodedata.normalize("NFKD", s)
            s = s.encode("ascii", "ignore").decode("ascii").lower()
            s = re.sub(r"[^a-z0-9]+", "-", s)
            return s.strip("-")
    """,
    test_inputs=[{"title": t} for t in [
        "Hello World", "Café au Lait", "Don't Panic!", "  Multiple   spaces  ", "C++ & Python: A Guide",
        "naïve résumé tips", "It's 2025's Best", "Crème Brûlée Recipe", "über-cool_design", "100% Pure",
        "---Already-slugged---", "", "Señor O’Brien’s Café", "I ❤ Python",
    ]],
)

item(
    id="median",
    category="statistics",
    ambiguous=True,
    spec="Return the median of a list of response times (in milliseconds) for the latency dashboard.",
    signature=sig("median", [P("values", "list[float]", "response times in ms, unsorted")],
                  "float | None", "the median response time"),
    axes=[
        axis("even_length", "Which value is the median when the list has an even number of elements.",
             "mean of the two middle values",
             ["lower of the two middle values (nearest-rank p50)", "upper of the two middle values"],
             [("lower of the two middle values (nearest-rank p50)", """
                def median(values):
                    if not values:
                        return None
                    s = sorted(values)
                    return s[(len(s) - 1) // 2]
              """),
              ("upper of the two middle values", """
                def median(values):
                    if not values:
                        return None
                    s = sorted(values)
                    return s[len(s) // 2]
              """)]),
        axis("empty_input", "What an empty list returns.",
             "return None (dashboard shows a dash)",
             ["raise an error (like statistics.median)", "return 0"],
             [("raise an error (like statistics.median)", """
                def median(values):
                    if not values:
                        raise ValueError("median of empty list")
                    s = sorted(values)
                    n = len(s)
                    m = n // 2
                    if n % 2:
                        return s[m]
                    return (s[m - 1] + s[m]) / 2
              """),
              ("return 0", """
                def median(values):
                    if not values:
                        return 0
                    s = sorted(values)
                    n = len(s)
                    m = n // 2
                    if n % 2:
                        return s[m]
                    return (s[m - 1] + s[m]) / 2
              """)]),
    ],
    intent=("Standard textbook median: sort the values; for an even count take the mean of the two middle values "
            "(e.g. [4, 1, 3, 2] -> 2.5). An empty list returns None, not an error and not 0, because the dashboard "
            "shows a dash for 'no data'. The input list is not guaranteed to be sorted."),
    reference="""
        def median(values):
            if not values:
                return None
            s = sorted(values)
            n = len(s)
            m = n // 2
            if n % 2:
                return s[m]
            return (s[m - 1] + s[m]) / 2
    """,
    test_inputs=[{"values": v} for v in [
        [3, 1, 2], [4, 1, 3, 2], [], [5], [10, 20], [1, 1, 1, 1], [7, 3, 9, 1, 5, 11], [2.5, 1.5],
        [100, 200, 300, 400, 500, 600], [-3, -1, -2, -4], [1, 2, 3, 4, 1000], [12, 15, 11, 30],
    ]],
)

item(
    id="age_on_date",
    category="dates",
    ambiguous=True,
    spec="Calculate a person's age in whole years as of a given date. Both dates are 'YYYY-MM-DD' strings.",
    signature=sig("age_on", [P("birthdate", "str", "ISO date of birth"), P("on", "str", "ISO date to compute the age at")],
                  "int", "age in whole years"),
    axes=[
        axis("leap_day_birthday", "When someone born on Feb 29 has their birthday in a non-leap year.",
             "on March 1 (still the previous age on Feb 28)",
             ["on February 28"],
             [("on February 28", """
                from datetime import date

                def age_on(birthdate: str, on: str) -> int:
                    b = date.fromisoformat(birthdate)
                    d = date.fromisoformat(on)
                    if d < b:
                        raise ValueError("date is before birth")
                    leap = d.year % 4 == 0 and (d.year % 100 != 0 or d.year % 400 == 0)
                    bday = (2, 28) if (b.month, b.day) == (2, 29) and not leap else (b.month, b.day)
                    years = d.year - b.year
                    if (d.month, d.day) < bday:
                        years -= 1
                    return years
              """)]),
        axis("method", "Calendar-based age vs elapsed time divided by an average year length.",
             "completed calendar years (age goes up exactly on the birthday)",
             ["floor(days elapsed / 365.25)"],
             [("floor(days elapsed / 365.25)", """
                from datetime import date

                def age_on(birthdate: str, on: str) -> int:
                    b = date.fromisoformat(birthdate)
                    d = date.fromisoformat(on)
                    if d < b:
                        raise ValueError("date is before birth")
                    return int((d - b).days // 365.25)
              """)]),
    ],
    intent=("Completed calendar years: the age goes up exactly on the birthday. Someone born on Feb 29 turns a year older "
            "on March 1 in non-leap years (on Feb 28 they are still the previous age). If `on` is before the birthdate, "
            "raise ValueError."),
    reference="""
        from datetime import date

        def age_on(birthdate: str, on: str) -> int:
            b = date.fromisoformat(birthdate)
            d = date.fromisoformat(on)
            if d < b:
                raise ValueError("date is before birth")
            leap = d.year % 4 == 0 and (d.year % 100 != 0 or d.year % 400 == 0)
            bday = (3, 1) if (b.month, b.day) == (2, 29) and not leap else (b.month, b.day)
            years = d.year - b.year
            if (d.month, d.day) < bday:
                years -= 1
            return years
    """,
    test_inputs=[{"birthdate": b, "on": o} for b, o in [
        ("2000-02-29", "2001-02-28"), ("2000-02-29", "2001-03-01"), ("2000-02-29", "2004-02-29"),
        ("2000-02-29", "2023-02-28"), ("2001-01-01", "2002-01-01"), ("1990-06-15", "2025-06-14"),
        ("1990-06-15", "2025-06-15"), ("1985-12-31", "2026-01-01"), ("2020-05-05", "2020-05-05"),
        ("2010-03-01", "2025-02-28"), ("2025-01-01", "2024-12-31"), ("1960-02-29", "2025-03-01"),
        ("2003-07-04", "2025-07-04"),
    ]],
)

item(
    id="parse_slash_date",
    category="dates",
    ambiguous=True,
    spec="Parse the date column from our supplier's CSV export (values look like '03/04/2025') and return it as an ISO 'YYYY-MM-DD' string.",
    signature=sig("parse_csv_date", [P("s", "str", "date string from the CSV")], "str", "ISO date 'YYYY-MM-DD'"),
    axes=[
        axis("field_order", "Whether '03/04/2025' is 3 April (DD/MM) or March 4 (MM/DD).",
             "DD/MM/YYYY (day first)",
             ["MM/DD/YYYY (US, month first)",
              "guess: day first if the first number is > 12, otherwise month first"],
             [("MM/DD/YYYY (US, month first)", """
                import re
                from datetime import date

                def parse_csv_date(s: str) -> str:
                    m = re.fullmatch(r"\\s*(\\d{1,2})/(\\d{1,2})/(\\d{4}|\\d{2})\\s*", s)
                    if not m:
                        raise ValueError(f"bad date: {s!r}")
                    mo, d, y = int(m[1]), int(m[2]), m[3]
                    year = 2000 + int(y) if len(y) == 2 else int(y)
                    return date(year, mo, d).isoformat()
              """),
              ("guess: day first if the first number is > 12, otherwise month first", """
                import re
                from datetime import date

                def parse_csv_date(s: str) -> str:
                    m = re.fullmatch(r"\\s*(\\d{1,2})/(\\d{1,2})/(\\d{4}|\\d{2})\\s*", s)
                    if not m:
                        raise ValueError(f"bad date: {s!r}")
                    a, b, y = int(m[1]), int(m[2]), m[3]
                    d, mo = (a, b) if a > 12 else (b, a)
                    year = 2000 + int(y) if len(y) == 2 else int(y)
                    return date(year, mo, d).isoformat()
              """)]),
        axis("two_digit_year", "How a two-digit year such as '75' is expanded.",
             "always 20YY",
             ["POSIX/strptime %y pivot: 69-99 -> 19YY, 00-68 -> 20YY"],
             [("POSIX/strptime %y pivot: 69-99 -> 19YY, 00-68 -> 20YY", """
                import re
                from datetime import date

                def parse_csv_date(s: str) -> str:
                    m = re.fullmatch(r"\\s*(\\d{1,2})/(\\d{1,2})/(\\d{4}|\\d{2})\\s*", s)
                    if not m:
                        raise ValueError(f"bad date: {s!r}")
                    d, mo, y = int(m[1]), int(m[2]), m[3]
                    year = int(y)
                    if len(y) == 2:
                        year += 1900 if year >= 69 else 2000
                    return date(year, mo, d).isoformat()
              """)]),
    ],
    intent=("The supplier is in Germany, so the format is always DD/MM/YYYY: '03/04/2025' is 3 April 2025 -> '2025-04-03'. "
            "Leading zeros are optional ('7/8/2025' -> '2025-08-07'); surrounding whitespace is ignored. Two-digit years "
            "mean 2000-2099 ('10/03/75' -> '2075-03-10'). Anything that isn't a valid calendar date in that format "
            "raises ValueError."),
    reference="""
        import re
        from datetime import date

        def parse_csv_date(s: str) -> str:
            m = re.fullmatch(r"\\s*(\\d{1,2})/(\\d{1,2})/(\\d{4}|\\d{2})\\s*", s)
            if not m:
                raise ValueError(f"bad date: {s!r}")
            d, mo, y = int(m[1]), int(m[2]), m[3]
            year = 2000 + int(y) if len(y) == 2 else int(y)
            return date(year, mo, d).isoformat()
    """,
    test_inputs=[{"s": s} for s in [
        "03/04/2025", "25/12/2024", "01/02/03", "12/11/2025", "7/8/2025", "31/01/2025", "15/06/99",
        "05/05/2025", "29/02/2024", "29/02/2023", "13/13/2025", "10/03/75", "1/12/2025", "2025-04-03",
    ]],
)

item(
    id="word_count",
    category="text",
    ambiguous=True,
    spec="Count the number of words in a student's essay so we can enforce the word limit.",
    signature=sig("count_words", [P("text", "str", "essay text")], "int", "number of words"),
    axes=[
        axis("hyphens", "Whether hyphenated compounds are one word or several.",
             "a hyphenated compound is one word (well-known = 1)",
             ["each hyphen-separated part is a separate word (well-known = 2)"],
             [("each hyphen-separated part is a separate word (well-known = 2)", """
                import re

                def count_words(text: str) -> int:
                    return len(re.findall(r"[^\\W_]+(?:['’][^\\W_]+)*", text))
              """)]),
        axis("apostrophes", "Whether contractions/possessives are one word.",
             "contractions and possessives are one word (don't = 1, John's = 1)",
             ["an apostrophe splits the word (don't = 2)"],
             [("an apostrophe splits the word (don't = 2)", """
                import re

                def count_words(text: str) -> int:
                    return len(re.findall(r"[^\\W_]+(?:-[^\\W_]+)*", text))
              """)]),
        axis("punctuation_tokens", "Whether whitespace-separated punctuation counts and whether punctuation without spaces joins words.",
             "only runs of letters/digits count; '&' or ' - ' are not words, and 'Hello...world' / 'yes—no' are 2 words",
             ["whatever str.split() returns (split on whitespace only)"],
             [("whatever str.split() returns (split on whitespace only)", """
                def count_words(text: str) -> int:
                    return len(text.split())
              """)]),
    ],
    intent=("A word is a run of letters/digits. Hyphenated compounds count as one word (state-of-the-art = 1) and so do "
            "contractions/possessives with ' or ’ (don't = 1, John's = 1). Stand-alone punctuation or symbols such as "
            "'&', '-', '—', '...' are not words, and punctuation without spaces still separates words "
            "('Hello...world' = 2, 'yes—no' = 2). Numbers count as words."),
    reference="""
        import re

        _WORD = re.compile(r"[^\\W_]+(?:['’-][^\\W_]+)*")

        def count_words(text: str) -> int:
            return len(_WORD.findall(text))
    """,
    test_inputs=[{"text": t} for t in [
        "Hello world", "A well-known fact", "Don't stop", "Rock & roll", "Wait - what?", "", "   ",
        "John's state-of-the-art car", "It's 2025, and we're ready.", "one\ntwo\tthree", "Hello...world",
        "e-mail me at 5 o'clock", "Yes—no", "The end.",
    ]],
)

item(
    id="truncate_preview",
    category="text",
    ambiguous=True,
    spec="Truncate a product description to max_len characters for the listing card, adding '...' when it gets cut off.",
    signature=sig("truncate", [P("text", "str", "full description"), P("max_len", "int", "character limit (always >= 4)")],
                  "str", "possibly shortened description"),
    axes=[
        axis("ellipsis_counting", "Whether the three dots count toward max_len.",
             "the result including '...' is at most max_len characters",
             ["cut the text to max_len characters, then append '...' (result can be max_len + 3)"],
             [("cut the text to max_len characters, then append '...' (result can be max_len + 3)", """
                def truncate(text: str, max_len: int) -> str:
                    if len(text) <= max_len:
                        return text
                    return text[:max_len] + "..."
              """)]),
        axis("word_boundary", "Whether to cut mid-word or back off to the previous space.",
             "hard cut at the character limit, even mid-word",
             ["back off to the last space so words aren't split (unless there is no space)"],
             [("back off to the last space so words aren't split (unless there is no space)", """
                def truncate(text: str, max_len: int) -> str:
                    if len(text) <= max_len:
                        return text
                    cut = text[: max_len - 3]
                    if text[max_len - 3] != " " and " " in cut:
                        cut = cut[: cut.rfind(" ")]
                    return cut.rstrip() + "..."
              """)]),
    ],
    intent=("If the text fits (len <= max_len) return it unchanged. Otherwise return the first max_len - 3 characters "
            "followed by '...', so the result is exactly max_len characters long including the dots. Cut at the exact "
            "character position even if that splits a word; don't strip spaces. max_len is always at least 4."),
    reference="""
        def truncate(text: str, max_len: int) -> str:
            if len(text) <= max_len:
                return text
            return text[: max_len - 3] + "..."
    """,
    test_inputs=[{"text": t, "max_len": n} for t, n in [
        ("Hello world, this is a long description", 10), ("Short", 10), ("Exactly10!", 10), ("Elevenchars", 10),
        ("", 5), ("Wireless noise-cancelling headphones", 20), ("abcdefghij", 4), ("The quick brown fox", 15),
        ("Supercalifragilistic", 8), ("One two three four five", 12), ("Hi there", 8), ("Hi there!", 8),
    ]],
)

item(
    id="percent_change",
    category="numbers",
    ambiguous=True,
    spec="Calculate the percentage change from last month's value to this month's value for the KPI dashboard, rounded to one decimal place.",
    signature=sig("percent_change", [P("old", "float", "last month's value"), P("new", "float", "this month's value")],
                  "float | None", "percentage change, e.g. 50.0 for +50%"),
    axes=[
        axis("zero_base", "What to return when last month's value is 0.",
             "None when new != 0 (shown as 'n/a'); 0.0 when both are 0",
             ["raise an error (division by zero)", "treat any rise from 0 as +100% (and any drop as -100%)"],
             [("raise an error (division by zero)", """
                def percent_change(old: float, new: float):
                    if old == 0:
                        raise ZeroDivisionError("old value is zero")
                    return round((new - old) / abs(old) * 100, 1)
              """),
              ("treat any rise from 0 as +100% (and any drop as -100%)", """
                def percent_change(old: float, new: float):
                    if old == 0:
                        return 100.0 if new > 0 else (-100.0 if new < 0 else 0.0)
                    return round((new - old) / abs(old) * 100, 1)
              """)]),
        axis("negative_base", "How to handle a negative starting value (e.g. a loss of -200 shrinking to -100).",
             "divide by |old| so improvement is positive (-200 -> -100 = +50.0)",
             ["divide by old as-is ((new - old) / old; -200 -> -100 = -50.0)"],
             [("divide by old as-is ((new - old) / old; -200 -> -100 = -50.0)", """
                def percent_change(old: float, new: float):
                    if old == 0:
                        return 0.0 if new == 0 else None
                    return round((new - old) / old * 100, 1)
              """)]),
    ],
    intent=("(new - old) / |old| * 100, rounded to 1 decimal with round(). Dividing by the absolute value means a "
            "negative metric moving up is a positive change (-200 -> -100 is +50.0). If old is 0: return 0.0 when new "
            "is also 0, otherwise return None (the dashboard shows 'n/a'); never raise."),
    reference="""
        def percent_change(old: float, new: float):
            if old == 0:
                return 0.0 if new == 0 else None
            return round((new - old) / abs(old) * 100, 1)
    """,
    test_inputs=[{"old": o, "new": n} for o, n in [
        (100, 150), (200, 150), (0, 50), (0, 0), (0, -20), (-200, -100), (-100, 50), (50, 50), (3, 4),
        (80, 0), (1.5, 1.2), (-50, -75), (7, 8),
    ]],
)

item(
    id="merge_intervals",
    category="algorithms",
    ambiguous=True,
    spec="Merge overlapping meeting time ranges into busy blocks. Each range is [start, end] in minutes since midnight.",
    signature=sig("merge_intervals", [P("intervals", "list[list[int]]", "[start, end] pairs, not necessarily sorted")],
                  "list[list[int]]", "merged [start, end] blocks"),
    axes=[axis(
        "touching", "Whether ranges that only touch (one ends at 600, the next starts at 600) are merged.",
        "touching ranges merge ([540,600] + [600,660] -> [540,660]); a 1-minute gap does not",
        ["only strictly overlapping ranges merge; touching ranges stay separate",
         "treat ranges as inclusive integer minutes, so [540,600] + [601,660] also merge"],
        [("only strictly overlapping ranges merge; touching ranges stay separate", """
            def merge_intervals(intervals):
                out = []
                for a, b in sorted([list(iv) for iv in intervals]):
                    if out and a < out[-1][1]:
                        out[-1][1] = max(out[-1][1], b)
                    else:
                        out.append([a, b])
                return out
         """),
         ("treat ranges as inclusive integer minutes, so [540,600] + [601,660] also merge", """
            def merge_intervals(intervals):
                out = []
                for a, b in sorted([list(iv) for iv in intervals]):
                    if out and a <= out[-1][1] + 1:
                        out[-1][1] = max(out[-1][1], b)
                    else:
                        out.append([a, b])
                return out
         """)],
    )],
    intent=("Back-to-back meetings form one busy block: ranges that overlap OR touch (end == next start) are merged. "
            "A gap of even one minute keeps them separate. Input may be unsorted; output is sorted by start, as a list "
            "of [start, end] lists. Empty input -> []."),
    reference="""
        def merge_intervals(intervals):
            out = []
            for a, b in sorted([list(iv) for iv in intervals]):
                if out and a <= out[-1][1]:
                    out[-1][1] = max(out[-1][1], b)
                else:
                    out.append([a, b])
            return out
    """,
    test_inputs=[{"intervals": v} for v in [
        [[540, 600], [600, 660]], [[540, 600], [601, 660]], [[540, 600], [570, 630]], [], [[60, 120]],
        [[700, 800], [540, 600], [590, 650]], [[1, 5], [2, 3]], [[1, 2], [2, 3], [3, 4]], [[0, 10], [10, 10]],
        [[100, 200], [300, 400], [200, 300]], [[5, 6], [1, 2], [3, 4]], [[0, 30], [30, 60], [61, 90]],
    ]],
)

item(
    id="top_k_ties",
    category="algorithms",
    ambiguous=True,
    spec="Return the names of the top k players on the leaderboard, highest score first.",
    signature=sig("top_k_players", [P("scores", "dict[str, int]", "player name -> score"), P("k", "int", "how many players")],
                  "list[str]", "player names, best first"),
    axes=[
        axis("cutoff_ties", "What happens when several players are tied at the k-th place.",
             "return exactly k names (fewer only if there are fewer players)",
             ["include everyone tied with the k-th score, even if that returns more than k names"],
             [("include everyone tied with the k-th score, even if that returns more than k names", """
                def top_k_players(scores, k):
                    ranked = sorted(scores, key=lambda name: (-scores[name], name))
                    if k <= 0:
                        return []
                    if k >= len(ranked):
                        return ranked
                    cutoff = scores[ranked[k - 1]]
                    return [n for n in ranked if scores[n] >= cutoff]
              """)]),
        axis("tie_order", "How tied players are ordered (and therefore who makes the cut).",
             "alphabetically by name",
             ["in the order they appear in the input (stable sort by score only)"],
             [("in the order they appear in the input (stable sort by score only)", """
                def top_k_players(scores, k):
                    if k <= 0:
                        return []
                    return sorted(scores, key=lambda name: -scores[name])[:k]
              """)]),
    ],
    intent=("Sort by score descending; break ties alphabetically by name (that also decides who makes the cut). Always "
            "return exactly min(k, number of players) names. k <= 0 returns []."),
    reference="""
        def top_k_players(scores, k):
            if k <= 0:
                return []
            ranked = sorted(scores, key=lambda name: (-scores[name], name))
            return ranked[:k]
    """,
    test_inputs=[
        {"scores": {"ann": 90, "bob": 85, "cat": 85, "dan": 70}, "k": 2},
        {"scores": {"zoe": 50, "amy": 50, "max": 40}, "k": 1},
        {"scores": {"ann": 90, "bob": 85, "cat": 80}, "k": 2},
        {"scores": {"ann": 90, "bob": 85}, "k": 5},
        {"scores": {}, "k": 3},
        {"scores": {"ann": 10}, "k": 0},
        {"scores": {"b": 10, "a": 10, "c": 10}, "k": 2},
        {"scores": {"x": -5, "y": -1, "z": -3}, "k": 2},
        {"scores": {"mia": 70, "leo": 90, "ivy": 90, "eli": 90}, "k": 2},
        {"scores": {"p1": 3, "p2": 2, "p3": 1}, "k": 3},
        {"scores": {"tom": 60, "sam": 75, "kim": 60, "ali": 60}, "k": 3},
        {"scores": {"solo": 42}, "k": 1},
    ],
)

item(
    id="password_strength",
    category="security",
    ambiguous=True,
    spec=("Classify a password as 'weak', 'medium', or 'strong'. A strong password is at least 12 characters long and "
          "contains uppercase letters, lowercase letters, digits, and symbols."),
    signature=sig("password_strength", [P("password", "str", "candidate password")], "str", "'weak', 'medium' or 'strong'"),
    axes=[
        axis("medium_rule", "What makes a password 'medium' (the spec only defines 'strong').",
             "at least 8 characters AND at least 3 of the 4 character classes",
             ["at least 8 characters, regardless of character classes",
              "at least 8 characters OR at least 3 character classes"],
             [("at least 8 characters, regardless of character classes", """
                def password_strength(password: str) -> str:
                    classes = sum([
                        any(c.isupper() for c in password),
                        any(c.islower() for c in password),
                        any(c.isdigit() for c in password),
                        any(not c.isalnum() for c in password),
                    ])
                    if len(password) >= 12 and classes == 4:
                        return "strong"
                    if len(password) >= 8:
                        return "medium"
                    return "weak"
              """),
              ("at least 8 characters OR at least 3 character classes", """
                def password_strength(password: str) -> str:
                    classes = sum([
                        any(c.isupper() for c in password),
                        any(c.islower() for c in password),
                        any(c.isdigit() for c in password),
                        any(not c.isalnum() for c in password),
                    ])
                    if len(password) >= 12 and classes == 4:
                        return "strong"
                    if len(password) >= 8 or classes >= 3:
                        return "medium"
                    return "weak"
              """)]),
        axis("symbol_definition", "Whether a space counts as a symbol.",
             "any character that is not a letter or digit, including spaces",
             ["only ASCII punctuation (string.punctuation); spaces don't count"],
             [("only ASCII punctuation (string.punctuation); spaces don't count", """
                import string

                def password_strength(password: str) -> str:
                    classes = sum([
                        any(c.isupper() for c in password),
                        any(c.islower() for c in password),
                        any(c.isdigit() for c in password),
                        any(c in string.punctuation for c in password),
                    ])
                    if len(password) >= 12 and classes == 4:
                        return "strong"
                    if len(password) >= 8 and classes >= 3:
                        return "medium"
                    return "weak"
              """)]),
    ],
    intent=("Four character classes: uppercase, lowercase, digit, symbol, where a symbol is ANY character that is not a "
            "letter or digit (spaces count as symbols). 'strong' = length >= 12 and all four classes. 'medium' = not "
            "strong, but length >= 8 and at least 3 of the 4 classes. Everything else is 'weak'."),
    reference="""
        def password_strength(password: str) -> str:
            classes = sum([
                any(c.isupper() for c in password),
                any(c.islower() for c in password),
                any(c.isdigit() for c in password),
                any(not c.isalnum() for c in password),
            ])
            if len(password) >= 12 and classes == 4:
                return "strong"
            if len(password) >= 8 and classes >= 3:
                return "medium"
            return "weak"
    """,
    test_inputs=[{"password": p} for p in [
        "password", "Password1", "Password1!", "Correct Horse 9", "Tr0ub4dor&3xyz", "abc", "", "ABCdef12",
        "aB3$", "aaaaaaaaaaaaaaaa", "my pass word 12", "Sh0rt!", "LongButSimplePassword", "Str0ng!Passw0rd",
    ]],
)

item(
    id="title_case",
    category="text",
    ambiguous=True,
    spec="Convert a blog headline to title case.",
    signature=sig("title_case", [P("headline", "str", "headline text")], "str", "headline in title case"),
    axes=[
        axis("small_words", "Whether short words (a, of, the, ...) stay lowercase.",
             "lowercase minor words (a, an, and, as, at, but, by, for, in, nor, of, on, or, the, to) unless first or last",
             ["capitalize every word"],
             [("capitalize every word", """
                def title_case(headline: str) -> str:
                    return " ".join(w[:1].upper() + w[1:] for w in headline.split())
              """)]),
        axis("existing_caps", "What happens to letters after the first one (acronyms like NASA, SQL).",
             "leave the rest of each word as typed (NASA stays NASA)",
             ["lowercase the rest of each word (NASA -> Nasa)"],
             [("lowercase the rest of each word (NASA -> Nasa)", """
                SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of", "on", "or", "the", "to"}

                def title_case(headline: str) -> str:
                    words = headline.split()
                    out = []
                    for i, w in enumerate(words):
                        lw = w.lower()
                        if 0 < i < len(words) - 1 and lw in SMALL:
                            out.append(lw)
                        else:
                            out.append(w.capitalize())
                    return " ".join(out)
              """)]),
        axis("last_word", "Whether a minor word at the very end is capitalized.",
             "first AND last words are always capitalized ('... Looking For')",
             ["only the first word is exempt ('... Looking for')"],
             [("only the first word is exempt ('... Looking for')", """
                SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of", "on", "or", "the", "to"}

                def title_case(headline: str) -> str:
                    words = headline.split()
                    out = []
                    for i, w in enumerate(words):
                        lw = w.lower()
                        if i > 0 and lw in SMALL:
                            out.append(lw)
                        else:
                            out.append(w[:1].upper() + w[1:])
                    return " ".join(out)
              """)]),
    ],
    intent=("Capitalize the first letter of every word but leave the remaining letters as typed (so acronyms such as NASA "
            "or SQL survive). These minor words are lowercased unless they are the first or last word: a, an, and, as, "
            "at, but, by, for, in, nor, of, on, or, the, to. Runs of whitespace collapse to single spaces and the result "
            "is trimmed."),
    reference="""
        SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of", "on", "or", "the", "to"}

        def title_case(headline: str) -> str:
            words = headline.split()
            out = []
            for i, w in enumerate(words):
                lw = w.lower()
                if 0 < i < len(words) - 1 and lw in SMALL:
                    out.append(lw)
                else:
                    out.append(w[:1].upper() + w[1:])
            return " ".join(out)
    """,
    test_inputs=[{"headline": h} for h in [
        "the lord of the rings", "a tale of two cities", "NASA launches new rocket", "what are you looking for",
        "harry potter and the chamber of secrets", "how to win friends", "war and peace", "in the beginning",
        "learning SQL in 10 days", "", "  extra   spaces here ", "something to look forward to",
        "an AI for the masses", "ALL CAPS HEADLINE",
    ]],
)

item(
    id="page_count",
    category="web",
    ambiguous=True,
    spec="Given the total number of search results and the page size, return how many pages the paginator should show.",
    signature=sig("page_count", [P("total_items", "int", "number of results"), P("page_size", "int", "results per page")],
                  "int", "number of pages"),
    axes=[axis(
        "zero_results", "How many pages to show when there are no results.",
        "1 (an empty first page that says 'No results')",
        ["0 pages"],
        [("0 pages", """
            def page_count(total_items: int, page_size: int) -> int:
                if page_size <= 0 or total_items < 0:
                    raise ValueError("invalid arguments")
                return -(-total_items // page_size)
         """)],
    )],
    intent=("Ceiling division: ceil(total_items / page_size). With zero results the paginator still shows 1 page "
            "(page 1 displays 'No results'), so return 1, not 0. page_size <= 0 or a negative total raises ValueError."),
    reference="""
        def page_count(total_items: int, page_size: int) -> int:
            if page_size <= 0 or total_items < 0:
                raise ValueError("invalid arguments")
            return max(1, -(-total_items // page_size))
    """,
    test_inputs=[{"total_items": t, "page_size": p} for t, p in [
        (0, 10), (1, 10), (10, 10), (11, 10), (95, 20), (100, 20), (101, 20), (5, 1), (0, 1), (7, 0),
        (1000, 25), (-1, 10),
    ]],
)

item(
    id="normalize_phone",
    category="data-cleaning",
    ambiguous=True,
    spec="Normalize the US phone numbers people type into the signup form so we store them in one consistent format.",
    signature=sig("normalize_phone", [P("raw", "str", "phone number as typed")], "str", "normalized phone number"),
    axes=[
        axis("output_format", "Which canonical format to store.",
             "E.164: '+15551234567'",
             ["'(555) 123-4567'", "'555-123-4567'"],
             [("'(555) 123-4567'", """
                def normalize_phone(raw: str) -> str:
                    digits = "".join(c for c in raw if c in "0123456789")
                    if len(digits) == 11 and digits[0] == "1":
                        digits = digits[1:]
                    if len(digits) != 10:
                        raise ValueError(f"not a US phone number: {raw!r}")
                    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
              """),
              ("'555-123-4567'", """
                def normalize_phone(raw: str) -> str:
                    digits = "".join(c for c in raw if c in "0123456789")
                    if len(digits) == 11 and digits[0] == "1":
                        digits = digits[1:]
                    if len(digits) != 10:
                        raise ValueError(f"not a US phone number: {raw!r}")
                    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
              """)]),
        axis("country_code", "Whether an 11-digit number with a leading 1 (country code) is accepted.",
             "accept and drop a leading country code 1 ('+1 555 123 4567', '1-555-123-4567')",
             ["only exactly 10 digits are valid; anything else is rejected"],
             [("only exactly 10 digits are valid; anything else is rejected", """
                def normalize_phone(raw: str) -> str:
                    digits = "".join(c for c in raw if c in "0123456789")
                    if len(digits) != 10:
                        raise ValueError(f"not a US phone number: {raw!r}")
                    return "+1" + digits
              """)]),
    ],
    intent=("Store E.164: '+1' followed by the 10-digit number, e.g. '+15551234567'. Ignore all formatting characters "
            "(spaces, dashes, dots, parentheses, '+'). A leading country code 1 is allowed (11 digits starting with 1). "
            "Anything that doesn't leave exactly 10 digits after that raises ValueError."),
    reference="""
        def normalize_phone(raw: str) -> str:
            digits = "".join(c for c in raw if c in "0123456789")
            if len(digits) == 11 and digits[0] == "1":
                digits = digits[1:]
            if len(digits) != 10:
                raise ValueError(f"not a US phone number: {raw!r}")
            return "+1" + digits
    """,
    test_inputs=[{"raw": r} for r in [
        "(555) 123-4567", "555.123.4567", "5551234567", "+1 555 123 4567", "1-555-123-4567", "15551234567",
        "555-1234", "+44 20 7946 0958", " 555 123 4567 ", "555-123-45678", "(212)555-0199", "+1 (415) 555-2671",
    ]],
)

item(
    id="letter_grade",
    category="education",
    ambiguous=True,
    spec=("Convert a student's percentage score to a letter grade: A for 90 and above, B for the 80s, C for the 70s, "
          "D for the 60s, and F below 60."),
    signature=sig("letter_grade", [P("score", "float", "percentage score, may have decimals")], "str", "'A'..'D' or 'F'"),
    axes=[
        axis("fractional_boundary", "Whether a fractional score like 89.5 is rounded before comparing to the cut-offs.",
             "round to the nearest whole number first, .5 rounds up (89.5 -> 90 -> A)",
             ["compare the raw score (89.5 is in the 80s -> B)"],
             [("compare the raw score (89.5 is in the 80s -> B)", """
                def letter_grade(score: float) -> str:
                    if score < 0:
                        raise ValueError("negative score")
                    if score >= 90:
                        return "A"
                    if score >= 80:
                        return "B"
                    if score >= 70:
                        return "C"
                    if score >= 60:
                        return "D"
                    return "F"
              """)]),
        axis("above_100", "Whether scores above 100 (extra credit) are valid.",
             "allowed; anything >= 90 is an A",
             ["invalid: raise an error"],
             [("invalid: raise an error", """
                import math

                def letter_grade(score: float) -> str:
                    if score < 0 or score > 100:
                        raise ValueError("score out of range")
                    s = math.floor(score + 0.5)
                    if s >= 90:
                        return "A"
                    if s >= 80:
                        return "B"
                    if s >= 70:
                        return "C"
                    if s >= 60:
                        return "D"
                    return "F"
              """)]),
    ],
    intent=("First round the score to the nearest whole number with .5 rounding up (89.5 -> 90 -> 'A', 89.4 -> 89 -> 'B', "
            "59.5 -> 60 -> 'D'), then apply the cut-offs 90/80/70/60. Scores above 100 are possible with extra credit "
            "and are an 'A'. A negative score raises ValueError."),
    reference="""
        import math

        def letter_grade(score: float) -> str:
            if score < 0:
                raise ValueError("negative score")
            s = math.floor(score + 0.5)
            if s >= 90:
                return "A"
            if s >= 80:
                return "B"
            if s >= 70:
                return "C"
            if s >= 60:
                return "D"
            return "F"
    """,
    test_inputs=[{"score": s} for s in
                 [95, 90, 89.5, 89.4, 80, 79.99, 70, 69.5, 60, 59.5, 59.4, 0, 100, 104, -1, 85.5]],
)

item(
    id="shipping_cost",
    category="commerce",
    ambiguous=True,
    spec=("Calculate the shipping cost: packages under 1 kg cost $5, packages between 1 and 5 kg cost $10, and heavier "
          "packages cost $20. Orders over $50 ship free."),
    signature=sig("shipping_cost", [P("weight_kg", "float", "package weight in kg"), P("order_total", "float", "order value in dollars")],
                  "float", "shipping cost in dollars"),
    axes=[
        axis("upper_weight_boundary", "Which tier a package of exactly 5 kg falls into.",
             "exactly 5 kg is $10 ('between 1 and 5' is inclusive)",
             ["exactly 5 kg is $20 (the $10 tier is 1 <= w < 5)"],
             [("exactly 5 kg is $20 (the $10 tier is 1 <= w < 5)", """
                def shipping_cost(weight_kg: float, order_total: float) -> float:
                    if weight_kg <= 0:
                        raise ValueError("weight must be positive")
                    if order_total > 50:
                        return 0.0
                    if weight_kg < 1:
                        return 5.0
                    if weight_kg < 5:
                        return 10.0
                    return 20.0
              """)]),
        axis("free_threshold", "Whether an order of exactly $50.00 ships free.",
             "no: strictly more than $50",
             ["yes: $50 or more"],
             [("yes: $50 or more", """
                def shipping_cost(weight_kg: float, order_total: float) -> float:
                    if weight_kg <= 0:
                        raise ValueError("weight must be positive")
                    if order_total >= 50:
                        return 0.0
                    if weight_kg < 1:
                        return 5.0
                    if weight_kg <= 5:
                        return 10.0
                    return 20.0
              """)]),
    ],
    intent=("Tiers: weight < 1 kg -> 5.0; 1 kg <= weight <= 5 kg -> 10.0 (exactly 5 kg is still $10); weight > 5 kg -> "
            "20.0. Free shipping (0.0) only when order_total is strictly greater than 50 (an order of exactly $50.00 "
            "pays shipping), and it applies regardless of weight. weight_kg <= 0 raises ValueError."),
    reference="""
        def shipping_cost(weight_kg: float, order_total: float) -> float:
            if weight_kg <= 0:
                raise ValueError("weight must be positive")
            if order_total > 50:
                return 0.0
            if weight_kg < 1:
                return 5.0
            if weight_kg <= 5:
                return 10.0
            return 20.0
    """,
    test_inputs=[{"weight_kg": w, "order_total": t} for w, t in [
        (0.5, 20), (1, 20), (5, 20), (5.01, 20), (4.99, 20), (2, 50), (2, 50.01), (12, 80), (0.99, 49.99),
        (5, 50), (10, 10), (0, 10), (3, 0),
    ]],
)

item(
    id="shift_length",
    category="time",
    ambiguous=True,
    spec="Given a work shift's start and end times as 'HH:MM' strings (24-hour clock), return the length of the shift in minutes.",
    signature=sig("shift_minutes", [P("start", "str", "start time 'HH:MM'"), P("end", "str", "end time 'HH:MM'")],
                  "int", "shift length in minutes"),
    axes=[
        axis("overnight", "What an end time earlier than the start time means (22:00 -> 06:00).",
             "the shift crosses midnight (22:00 -> 06:00 = 480)",
             ["plain subtraction, giving a negative number", "absolute difference (22:00 -> 06:00 = 960)"],
             [("plain subtraction, giving a negative number", """
                def shift_minutes(start: str, end: str) -> int:
                    def mins(t):
                        h, m = t.split(":")
                        h, m = int(h), int(m)
                        if not (0 <= h < 24 and 0 <= m < 60):
                            raise ValueError(f"bad time {t!r}")
                        return h * 60 + m
                    return mins(end) - mins(start)
              """),
              ("absolute difference (22:00 -> 06:00 = 960)", """
                def shift_minutes(start: str, end: str) -> int:
                    def mins(t):
                        h, m = t.split(":")
                        h, m = int(h), int(m)
                        if not (0 <= h < 24 and 0 <= m < 60):
                            raise ValueError(f"bad time {t!r}")
                        return h * 60 + m
                    return abs(mins(end) - mins(start))
              """)]),
        axis("equal_times", "What identical start and end times mean.",
             "0 minutes",
             ["a full 24-hour shift (1440)"],
             [("a full 24-hour shift (1440)", """
                def shift_minutes(start: str, end: str) -> int:
                    def mins(t):
                        h, m = t.split(":")
                        h, m = int(h), int(m)
                        if not (0 <= h < 24 and 0 <= m < 60):
                            raise ValueError(f"bad time {t!r}")
                        return h * 60 + m
                    d = (mins(end) - mins(start)) % 1440
                    return d if d else 1440
              """)]),
    ],
    intent=("An end time earlier than the start means the shift ran past midnight: 22:00 -> 06:00 is 480 minutes. "
            "Identical start and end is 0 minutes (we never schedule 24-hour shifts). Single-digit hours like '9:05' "
            "are fine; an hour outside 0-23 or minute outside 0-59 raises ValueError."),
    reference="""
        def shift_minutes(start: str, end: str) -> int:
            def mins(t):
                h, m = t.split(":")
                h, m = int(h), int(m)
                if not (0 <= h < 24 and 0 <= m < 60):
                    raise ValueError(f"bad time {t!r}")
                return h * 60 + m
            return (mins(end) - mins(start)) % 1440
    """,
    test_inputs=[{"start": s, "end": e} for s, e in [
        ("09:00", "17:00"), ("22:00", "06:00"), ("23:30", "00:15"), ("08:00", "08:00"), ("00:00", "23:59"),
        ("12:00", "11:59"), ("07:15", "15:45"), ("00:00", "00:00"), ("18:30", "02:30"), ("25:00", "03:00"),
        ("9:05", "17:00"),
    ]],
)

item(
    id="split_full_name",
    category="people",
    ambiguous=True,
    spec="Split a customer's full name into a first name and a last name for the CRM import.",
    signature=sig("split_name", [P("full_name", "str", "full name as entered")],
                  "dict", "{'first': str, 'last': str}"),
    axes=[
        axis("middle_names", "Where middle names / extra words go.",
             "everything except the final word is the first name ('Mary Jane Watson' -> 'Mary Jane' / 'Watson')",
             ["drop middle names (first word / last word only)",
              "everything after the first word is the last name ('Mary' / 'Jane Watson')"],
             [("drop middle names (first word / last word only)", """
                def split_name(full_name: str) -> dict:
                    parts = full_name.split()
                    if not parts:
                        return {"first": "", "last": ""}
                    if len(parts) == 1:
                        return {"first": parts[0], "last": ""}
                    return {"first": parts[0], "last": parts[-1]}
              """),
              ("everything after the first word is the last name ('Mary' / 'Jane Watson')", """
                def split_name(full_name: str) -> dict:
                    parts = full_name.split()
                    if not parts:
                        return {"first": "", "last": ""}
                    if len(parts) == 1:
                        return {"first": parts[0], "last": ""}
                    return {"first": parts[0], "last": " ".join(parts[1:])}
              """)]),
        axis("single_word", "What a one-word name ('Cher') becomes.",
             "first name = the word, last name = ''",
             ["last name = the word, first name = ''", "reject it with an error"],
             [("last name = the word, first name = ''", """
                def split_name(full_name: str) -> dict:
                    parts = full_name.split()
                    if not parts:
                        return {"first": "", "last": ""}
                    if len(parts) == 1:
                        return {"first": "", "last": parts[0]}
                    return {"first": " ".join(parts[:-1]), "last": parts[-1]}
              """),
              ("reject it with an error", """
                def split_name(full_name: str) -> dict:
                    parts = full_name.split()
                    if not parts:
                        return {"first": "", "last": ""}
                    if len(parts) == 1:
                        raise ValueError("need at least two names")
                    return {"first": " ".join(parts[:-1]), "last": parts[-1]}
              """)]),
    ],
    intent=("Collapse whitespace. The last name is the final word; everything before it (including middle names) is the "
            "first name: 'Mary Jane Watson' -> first 'Mary Jane', last 'Watson'; 'Ludwig van Beethoven' -> 'Ludwig van' / "
            "'Beethoven'. A single word is a first name with an empty last name. Empty input -> both empty. Return a dict "
            "with exactly the keys 'first' and 'last'."),
    reference="""
        def split_name(full_name: str) -> dict:
            parts = full_name.split()
            if not parts:
                return {"first": "", "last": ""}
            if len(parts) == 1:
                return {"first": parts[0], "last": ""}
            return {"first": " ".join(parts[:-1]), "last": parts[-1]}
    """,
    test_inputs=[{"full_name": n} for n in [
        "John Smith", "Mary Jane Watson", "Cher", "  Ada   Lovelace ", "Ludwig van Beethoven",
        "Juan Carlos de la Cruz", "", "Prince", "Martin Luther King Jr.", "Jean-Luc Picard", "Grace Brewster Murray Hopper",
    ]],
)

item(
    id="currency_format",
    category="money",
    ambiguous=True,
    spec="Format a dollar amount for display on an invoice, e.g. 1234.5 -> '$1,234.50'.",
    signature=sig("format_currency", [P("amount", "float", "amount in dollars, may be negative")], "str", "formatted amount"),
    axes=[
        axis("negative_format", "How negative amounts (credits/refunds) are shown.",
             "accounting style in parentheses: '($1,234.50)'",
             ["leading minus before the dollar sign: '-$1,234.50'", "minus after the dollar sign: '$-1,234.50'"],
             [("leading minus before the dollar sign: '-$1,234.50'", """
                from decimal import Decimal, ROUND_HALF_UP

                def format_currency(amount: float) -> str:
                    q = Decimal(repr(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    s = f"${abs(q):,.2f}"
                    return "-" + s if q < 0 else s
              """),
              ("minus after the dollar sign: '$-1,234.50'", """
                from decimal import Decimal, ROUND_HALF_UP

                def format_currency(amount: float) -> str:
                    q = Decimal(repr(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    return f"${q:,.2f}" if q < 0 else f"${abs(q):,.2f}"
              """)]),
        axis("half_cent_rounding", "How half-cent amounts like 2.675 or 1.005 are rounded.",
             "round the decimal value as written, half away from zero (2.675 -> $2.68, 1.005 -> $1.01)",
             ["whatever float formatting gives (f'{x:.2f}': 2.675 -> $2.67, 1.005 -> $1.00)"],
             [("whatever float formatting gives (f'{x:.2f}': 2.675 -> $2.67, 1.005 -> $1.00)", """
                def format_currency(amount: float) -> str:
                    s = f"${abs(amount):,.2f}"
                    return f"({s})" if amount < 0 and s != "$0.00" else s
              """)]),
    ],
    intent=("'$' + thousands separators + exactly 2 decimals. Negative amounts (credits) use accounting parentheses: "
            "-1234.5 -> '($1,234.50)'. Round the amount as the decimal number that was written (use its repr), half away "
            "from zero: 2.675 -> '$2.68', 1.005 -> '$1.01', 0.125 -> '$0.13'. Anything that rounds to zero is '$0.00' "
            "(never '($0.00)')."),
    reference="""
        from decimal import Decimal, ROUND_HALF_UP

        def format_currency(amount: float) -> str:
            q = Decimal(repr(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            s = f"${abs(q):,.2f}"
            return f"({s})" if q < 0 else s
    """,
    test_inputs=[{"amount": a} for a in
                 [1234.5, 0, -1234.5, 1000000, 2.675, 1.005, -0.5, 0.125, 99.999, -42.0, 0.004, -0.004, 1234567.891]],
)

item(
    id="human_file_size",
    category="formatting",
    ambiguous=True,
    spec="Format a file size in bytes as a short human-readable string like '1.5 MB' for the file browser.",
    signature=sig("human_size", [P("num_bytes", "int", "size in bytes, >= 0")], "str", "human-readable size"),
    axes=[
        axis("base", "Whether 1 KB is 1024 or 1000 bytes.",
             "binary: 1 KB = 1024 bytes (labelled KB/MB/GB/TB)",
             ["decimal SI: 1 KB = 1000 bytes"],
             [("decimal SI: 1 KB = 1000 bytes", """
                def human_size(num_bytes: int) -> str:
                    if num_bytes < 0:
                        raise ValueError("negative size")
                    units = ["B", "KB", "MB", "GB", "TB"]
                    if num_bytes < 1000:
                        return f"{num_bytes} B"
                    size = float(num_bytes)
                    i = 0
                    while size >= 1000 and i < len(units) - 1:
                        size /= 1000
                        i += 1
                    return f"{size:.1f} {units[i]}"
              """)]),
        axis("trailing_zero", "Whether whole values keep the '.0'.",
             "always one decimal place ('1.0 KB')",
             ["drop a trailing '.0' ('1 KB')"],
             [("drop a trailing '.0' ('1 KB')", """
                def human_size(num_bytes: int) -> str:
                    if num_bytes < 0:
                        raise ValueError("negative size")
                    units = ["B", "KB", "MB", "GB", "TB"]
                    if num_bytes < 1024:
                        return f"{num_bytes} B"
                    size = float(num_bytes)
                    i = 0
                    while size >= 1024 and i < len(units) - 1:
                        size /= 1024
                        i += 1
                    s = f"{size:.1f}"
                    if s.endswith(".0"):
                        s = s[:-2]
                    return f"{s} {units[i]}"
              """)]),
        axis("unit_labels", "Which unit labels binary sizes use.",
             "KB, MB, GB, TB",
             ["IEC labels KiB, MiB, GiB, TiB"],
             [("IEC labels KiB, MiB, GiB, TiB", """
                def human_size(num_bytes: int) -> str:
                    if num_bytes < 0:
                        raise ValueError("negative size")
                    units = ["B", "KiB", "MiB", "GiB", "TiB"]
                    if num_bytes < 1024:
                        return f"{num_bytes} B"
                    size = float(num_bytes)
                    i = 0
                    while size >= 1024 and i < len(units) - 1:
                        size /= 1024
                        i += 1
                    return f"{size:.1f} {units[i]}"
              """)]),
    ],
    intent=("Use 1024-based units but label them B, KB, MB, GB, TB (the way Windows Explorer does). Under 1024 bytes "
            "show the integer with ' B' ('512 B', '0 B', '1000 B'). Otherwise divide by 1024 until the value is below "
            "1024 (stop at TB) and show exactly one decimal place, keeping '.0' ('1.0 KB', '1.5 KB'), using Python's "
            "f'{x:.1f}' formatting. Negative input raises ValueError."),
    reference="""
        def human_size(num_bytes: int) -> str:
            if num_bytes < 0:
                raise ValueError("negative size")
            units = ["B", "KB", "MB", "GB", "TB"]
            if num_bytes < 1024:
                return f"{num_bytes} B"
            size = float(num_bytes)
            i = 0
            while size >= 1024 and i < len(units) - 1:
                size /= 1024
                i += 1
            return f"{size:.1f} {units[i]}"
    """,
    test_inputs=[{"num_bytes": b} for b in [
        0, 512, 1000, 1023, 1024, 1536, 1048576, 5000000, 1073741824, 1500000000, 1099511627776, 123456789, 10240,
    ]],
)

item(
    id="week_number",
    category="dates",
    ambiguous=True,
    spec="Return the week number of the year for a given date ('YYYY-MM-DD'); we use it to group orders in the weekly sales report.",
    signature=sig("week_number", [P("day", "str", "ISO date")], "int", "week number"),
    axes=[axis(
        "week_system", "Which week-numbering convention to use.",
        "ISO 8601 weeks (Monday start; week 1 contains the first Thursday; 2021-01-01 is week 53)",
        ["US convention, Sunday-start weeks, days before the first Sunday are week 0 (strftime %U)",
         "Monday-start weeks, days before the first Monday are week 0 (strftime %W)",
         "simple: (day_of_year - 1) // 7 + 1"],
        [("US convention, Sunday-start weeks, days before the first Sunday are week 0 (strftime %U)", """
            from datetime import date

            def week_number(day: str) -> int:
                return int(date.fromisoformat(day).strftime("%U"))
         """),
         ("Monday-start weeks, days before the first Monday are week 0 (strftime %W)", """
            from datetime import date

            def week_number(day: str) -> int:
                return int(date.fromisoformat(day).strftime("%W"))
         """),
         ("simple: (day_of_year - 1) // 7 + 1", """
            from datetime import date

            def week_number(day: str) -> int:
                return (date.fromisoformat(day).timetuple().tm_yday - 1) // 7 + 1
         """)],
    )],
    intent=("ISO 8601 week numbers, the same as date.isocalendar().week: weeks start on Monday and week 1 is the week "
            "containing the year's first Thursday. So 2021-01-01 is week 53 (of 2020) and 2024-12-30 is week 1 (of "
            "2025). Return just the week number."),
    reference="""
        from datetime import date

        def week_number(day: str) -> int:
            return date.fromisoformat(day).isocalendar()[1]
    """,
    test_inputs=[{"day": d} for d in [
        "2021-01-01", "2024-12-30", "2025-01-01", "2025-06-15", "2020-12-31", "2026-01-04", "2025-03-03",
        "2023-01-01", "2024-02-29", "2025-12-29", "2027-01-01", "2025-07-04",
    ]],
)

item(
    id="cart_discounts",
    category="commerce",
    ambiguous=True,
    spec="Compute the final price of a shopping cart: members get 10% off, and customers with a coupon get $5 off.",
    signature=sig("final_price", [P("subtotal", "float", "cart subtotal in dollars"),
                                  P("is_member", "bool", "customer has a membership"),
                                  P("has_coupon", "bool", "customer applied the $5 coupon")],
                  "float", "amount to charge, in dollars"),
    axes=[
        axis("order", "Whether the 10% or the $5 is applied first when both apply.",
             "10% member discount first, then the $5 coupon ($100 -> $85.00)",
             ["$5 coupon first, then 10% off ($100 -> $85.50)"],
             [("$5 coupon first, then 10% off ($100 -> $85.50)", """
                from decimal import Decimal, ROUND_HALF_UP

                def final_price(subtotal: float, is_member: bool, has_coupon: bool) -> float:
                    p = Decimal(repr(subtotal))
                    if has_coupon:
                        p = p - 5
                    if is_member:
                        p = p * Decimal("0.9")
                    if p < 0:
                        p = Decimal(0)
                    return float(p.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
              """)]),
        axis("floor_at_zero", "What happens when the coupon is worth more than the cart.",
             "never charge less than $0.00",
             ["allow a negative result"],
             [("allow a negative result", """
                from decimal import Decimal, ROUND_HALF_UP

                def final_price(subtotal: float, is_member: bool, has_coupon: bool) -> float:
                    p = Decimal(repr(subtotal))
                    if is_member:
                        p = p * Decimal("0.9")
                    if has_coupon:
                        p = p - 5
                    return float(p.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
              """)]),
    ],
    intent=("Apply the 10% member discount first, then subtract the $5 coupon. The price never goes below 0.00. Round the "
            "final amount to cents, half-up (work in decimal, not binary float)."),
    reference="""
        from decimal import Decimal, ROUND_HALF_UP

        def final_price(subtotal: float, is_member: bool, has_coupon: bool) -> float:
            p = Decimal(repr(subtotal))
            if is_member:
                p = p * Decimal("0.9")
            if has_coupon:
                p = p - 5
            if p < 0:
                p = Decimal(0)
            return float(p.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    """,
    test_inputs=[{"subtotal": s, "is_member": m, "has_coupon": c} for s, m, c in [
        (100, True, True), (100, True, False), (100, False, True), (100, False, False), (3, False, True),
        (4, True, True), (50, True, True), (5, False, True), (19.99, True, True), (0, True, True),
        (5.5, True, True), (0.01, False, False),
    ]],
)

item(
    id="moving_average",
    category="statistics",
    ambiguous=True,
    spec="Compute the moving average of a daily sales series with a given window size (e.g. a 7-day moving average).",
    signature=sig("moving_average", [P("values", "list[float]", "daily sales, oldest first"), P("window", "int", "window size in days")],
                  "list", "moving-average series"),
    axes=[
        axis("warmup", "What to output for the first window-1 days, before a full window exists.",
             "same length as input; early days average whatever days are available so far",
             ["only full windows (output has len(values) - window + 1 entries)",
              "same length, with None for the first window-1 days"],
             [("only full windows (output has len(values) - window + 1 entries)", """
                def moving_average(values, window):
                    if window <= 0:
                        raise ValueError("window must be positive")
                    return [sum(values[i - window + 1: i + 1]) / window for i in range(window - 1, len(values))]
              """),
              ("same length, with None for the first window-1 days", """
                def moving_average(values, window):
                    if window <= 0:
                        raise ValueError("window must be positive")
                    return [None if i < window - 1 else sum(values[i - window + 1: i + 1]) / window
                            for i in range(len(values))]
              """)]),
        axis("alignment", "Whether the window trails the current day or is centred on it.",
             "trailing: today and the previous window-1 days",
             ["centred on the current day (truncated at the edges)"],
             [("centred on the current day (truncated at the edges)", """
                def moving_average(values, window):
                    if window <= 0:
                        raise ValueError("window must be positive")
                    out = []
                    for i in range(len(values)):
                        lo = max(0, i - (window - 1) // 2)
                        hi = min(len(values), i - (window - 1) // 2 + window)
                        chunk = values[lo:hi]
                        out.append(sum(chunk) / len(chunk))
                    return out
              """)]),
    ],
    intent=("Trailing window: the value for day i averages days max(0, i-window+1)..i. The output has the same length as "
            "the input; for the first window-1 days, average over the days available so far (day 0 is just its own "
            "value). A window larger than the series is fine. window <= 0 raises ValueError. Empty input -> []."),
    reference="""
        def moving_average(values, window):
            if window <= 0:
                raise ValueError("window must be positive")
            out = []
            for i in range(len(values)):
                chunk = values[max(0, i - window + 1): i + 1]
                out.append(sum(chunk) / len(chunk))
            return out
    """,
    test_inputs=[{"values": v, "window": w} for v, w in [
        ([1, 2, 3, 4, 5], 3), ([10, 20, 30], 1), ([], 3), ([5], 3), ([2, 4, 6, 8], 2), ([1, 2, 3], 5),
        ([3, 3, 3, 3, 3, 3, 3], 7), ([10, 0, 10, 0, 10], 3), ([1, 2, 3, 4, 5, 6, 7, 8], 4), ([100, 200], 3),
        ([1, 2], 0), ([7, 14, 21, 28, 35, 42, 49, 56, 63], 7),
    ]],
)

# ---------------------------------------------------------------------------
# Clear controls (should NOT trigger clarifying questions)
# ---------------------------------------------------------------------------

item(
    id="ctrl_sum_ints",
    category="control",
    ambiguous=False,
    spec="Return the sum of a list of integers. An empty list returns 0.",
    signature=sig("sum_ints", [P("nums", "list[int]", "integers")], "int", "their sum"),
    intent="Plain integer sum; empty list -> 0. Nothing else to clarify.",
    reference="""
        def sum_ints(nums: list[int]) -> int:
            return sum(nums)
    """,
    test_inputs=[{"nums": v} for v in [
        [], [1], [1, 2, 3], [-1, 1], [-5, -10], [0, 0, 0], [10**12, 10**12], [7, -3, 2, 9], list(range(100)), [42],
    ]],
)

item(
    id="ctrl_c_to_f",
    category="control",
    ambiguous=False,
    spec="Convert a temperature from Celsius to Fahrenheit using F = C × 9/5 + 32, rounded to 2 decimal places.",
    signature=sig("celsius_to_fahrenheit", [P("c", "float", "degrees Celsius")], "float", "degrees Fahrenheit"),
    intent="F = C * 9/5 + 32, then round(F, 2). Inputs never produce half-way rounding cases.",
    reference="""
        def celsius_to_fahrenheit(c: float) -> float:
            return round(c * 9 / 5 + 32, 2)
    """,
    test_inputs=[{"c": v} for v in [0, 100, -40, 37, 36.6, -273.15, 21.5, 1, -17.8, 15, 4.4]],
)

item(
    id="ctrl_leap_year",
    category="control",
    ambiguous=False,
    spec=("Return True if a year is a leap year in the Gregorian calendar: years divisible by 4 are leap years, except "
          "years divisible by 100, which are leap years only if they are also divisible by 400."),
    signature=sig("is_leap_year", [P("year", "int", "positive year")], "bool", "whether it is a leap year"),
    intent="Exactly the stated Gregorian rule, applied to any positive year (proleptic).",
    reference="""
        def is_leap_year(year: int) -> bool:
            return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    """,
    test_inputs=[{"year": y} for y in [2000, 1900, 2024, 2023, 2100, 2400, 1996, 1, 4, 1800, 2025]],
)

item(
    id="ctrl_fizzbuzz",
    category="control",
    ambiguous=False,
    spec=("Return a list of strings for the numbers 1 to n: 'Fizz' for multiples of 3, 'Buzz' for multiples of 5, "
          "'FizzBuzz' for multiples of both, and otherwise the number itself as a string. n = 0 returns an empty list."),
    signature=sig("fizzbuzz", [P("n", "int", "upper bound, >= 0")], "list[str]", "the FizzBuzz sequence"),
    intent="Classic FizzBuzz for 1..n inclusive; n = 0 -> [].",
    reference="""
        def fizzbuzz(n: int) -> list[str]:
            out = []
            for i in range(1, n + 1):
                if i % 15 == 0:
                    out.append("FizzBuzz")
                elif i % 3 == 0:
                    out.append("Fizz")
                elif i % 5 == 0:
                    out.append("Buzz")
                else:
                    out.append(str(i))
            return out
    """,
    test_inputs=[{"n": n} for n in [0, 1, 2, 3, 5, 10, 15, 16, 30, 31]],
)

item(
    id="ctrl_count_char",
    category="control",
    ambiguous=False,
    spec="Return how many times the single character ch appears in the string s. Matching is case-sensitive.",
    signature=sig("count_char", [P("s", "str", "text to search"), P("ch", "str", "a single character")],
                  "int", "number of occurrences"),
    intent="Case-sensitive count of ch in s; ch is always exactly one character.",
    reference="""
        def count_char(s: str, ch: str) -> int:
            return s.count(ch)
    """,
    test_inputs=[{"s": s, "ch": c} for s, c in [
        ("banana", "a"), ("banana", "A"), ("", "x"), ("aaaa", "a"), ("Hello World", "o"), ("Hello World", "l"),
        ("Mississippi", "s"), ("abc", "d"), ("a b c", " "), ("ÉéÉ", "É"),
    ]],
)

item(
    id="ctrl_reverse_words",
    category="control",
    ambiguous=False,
    spec=("Reverse the order of the words in a sentence. Words are separated by single spaces and there are no leading "
          "or trailing spaces; return the reversed words joined by single spaces."),
    signature=sig("reverse_words", [P("sentence", "str", "words separated by single spaces")], "str", "words in reverse order"),
    intent="Split on single spaces, reverse the word order, join with single spaces. Empty string -> empty string.",
    reference="""
        def reverse_words(sentence: str) -> str:
            return " ".join(reversed(sentence.split(" "))) if sentence else ""
    """,
    test_inputs=[{"sentence": s} for s in [
        "hello world", "one", "", "the quick brown fox", "a b c d e", "Hello, world!", "keep CASE as Is",
        "1 2 3", "racecar", "first second",
    ]],
)


def main() -> None:
    out = HERE / "specs.json"
    out.write_text(json.dumps(ITEMS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    n_amb = sum(i["ambiguous"] for i in ITEMS)
    print(f"wrote {out} ({len(ITEMS)} items: {n_amb} ambiguous, {len(ITEMS) - n_amb} controls)")


if __name__ == "__main__":
    main()
