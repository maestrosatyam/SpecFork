# SpecFork ambiguity benchmark

A small, hand-curated set of natural-language function specs for evaluating SpecFork against
baselines (e.g. "single sample, no questions", "ask the LLM what's ambiguous"). It measures two things:

1. **Detection / resolution on ambiguous specs**: does the system notice the real points of
   disagreement, ask about them, and (once a simulated user answers from `intent`) end up with
   code that matches `reference`?
2. **False alarms on clear specs**: control items should *not* produce clarifying questions.

## Contents

| file | purpose |
|---|---|
| `specs.json` | the dataset (32 items: 26 ambiguous, 6 clear controls) |
| `build_specs.py` | source of truth. Items are written as Python literals so the reference code stays readable. Run it to regenerate `specs.json` |
| `validate.py` | sanity checks; must pass before the dataset is used |

```bash
.venv/bin/python evals/benchmark/build_specs.py   # regenerate specs.json
.venv/bin/python evals/benchmark/validate.py      # summary table, exit 1 on any problem
.venv/bin/python evals/benchmark/validate.py -v   # also print every reference output
```

Totals: 52 ambiguity axes, 70 alternative reference implementations, 397 test inputs.
Domains: money, numbers, dates/time, text, data cleaning, statistics, algorithms, commerce,
security, web, people, education, formatting.

## How it was built

All of it was hand-written for the Nebius x NVIDIA hackathon on 2026-10-29 by the SpecFork team.
No LLM generated or filtered any of the items, and none of the specs were tuned against SpecFork's output.
Selection criteria for ambiguous items:

- The spec reads like something a PM or developer would actually type (1-3 sentences) and does
  **not** mention how the ambiguity is resolved.
- Each ambiguity is one that competent engineers really do resolve differently, and that changes
  observable output on ordinary inputs, e.g. who gets the leftover cent, ISO vs US week numbers,
  1000 vs 1024 bytes, DD/MM vs MM/DD. Items whose only ambiguity is error handling were avoided.
  Where error behaviour is specified in `intent`, it is secondary.
- The hidden `intent` is a fixed, plausible choice. It is not always the most popular one (e.g.
  `page_count` returns 1 for zero results, `round_temperature` rounds ties away from zero), so a
  system can't score well by guessing the majority convention without asking.

Control items state every rule explicitly (sum of ints, Celsius to Fahrenheit with rounding, the
Gregorian leap-year rule, FizzBuzz, case-sensitive character count, reversing words).

## Item fields

```jsonc
{
  "id": "bill_split",                 // unique
  "category": "money",                // domain tag; "control" for clear items
  "ambiguous": true,                  // false for controls
  "spec": "...",                      // what the user types; never reveals the resolution
  "signature": {"name": "split_bill",
                "params": [{"name": "total", "type": "float", "description": "..."}, ...],
                "returns": {"type": "list[float]", "description": "..."}},
  "axes": [                           // [] for controls
    {"id": "leftover_cents",
     "description": "what the ambiguity is about",
     "intended": "the interpretation the user meant (also interpretations[0])",
     "interpretations": ["intended", "alternative 1", ...],
     "alt_references": [             // one per non-intended interpretation
       {"interpretation": "alternative 1",
        "code": "def split_bill(...): ..."}   // = reference with ONLY this axis flipped
     ]}
  ],
  "intent": "full hidden clarification, written so a simulated user can answer any clarifying question",
  "reference": "def split_bill(total: float, n: int) -> list[float]: ...",   // ground truth
  "test_inputs": [{"total": 100, "n": 3}, ...]  // 10-20 kwargs dicts, keys = param names
}
```

Conventions:

- Arguments are JSON-only types (int, float, str, bool, list, dict, None). Dates are ISO
  `"YYYY-MM-DD"` strings, times are `"HH:MM"`.
- References and alternatives use only the standard library, are deterministic, and run in
  well under a millisecond per input.
- A test input may legitimately make the reference raise (e.g. `ValueError` for `n = 0` when
  the intent says so). The expected outcome is then "raises <ExceptionType>".
- Each alt reference differs from `reference` on exactly one axis, so the set
  `{reference} ∪ alt_references` gives ground-truth behavioural clusters. These can be used to
  score SpecFork's clustering (do impls implementing the same interpretation land together?) and
  its questions (does it ask about every axis?).
- Comparisons in `validate.py` normalise numbers (`2 == 2.0`, 9-decimal rounding), treat tuples
  as lists, and map exceptions to their type name. If you score with exact `repr` equality, expect
  int/float differences like `2` vs `2.0` (e.g. `median`) to split clusters.

## What `validate.py` checks

- required fields, unique ids, 10-20 unique test inputs whose keys match the signature;
- the reference loads in a fresh namespace, defines the named function, never times out
  (2 s per call via `SIGALRM`), returns JSON-serialisable values, is deterministic, and doesn't
  raise on every input;
- ambiguous items have ≥ 1 axis; each axis has ≥ 2 interpretations, a valid `intended`, and an
  alt reference for every non-intended interpretation;
- **every alt reference disagrees with the reference on at least one test input**, so the test
  inputs really do separate the interpretations (`min_diff` column);
- control items have no axes.

## Limitations

- **Small.** 32 items cannot support fine-grained statistical claims. Report per-item results
  and confidence intervals rather than single headline numbers.
- **Author-written, single author.** The specs, the chosen "intended" readings, and the axes
  reflect one person's idea of what's ambiguous. There may be real ambiguities we missed (and a
  system that finds them is not wrong), and some listed axes may be ones that most LLMs resolve the
  same way, so they never show up as disagreement.
- **Possible bias toward SpecFork's method.** Axes were picked because they change output on
  concrete inputs, which is exactly what execution-based clustering detects. Ambiguities about
  performance, style, API shape, or side effects are out of scope.
- **Arbitrary intents.** When a clarification is a coin flip (e.g. Feb 29 birthdays on Mar 1 vs
  Feb 28), a system that doesn't ask can only get it right by luck. That's the point, but scores on
  "no-question" baselines therefore have high variance.
- **Hand-picked test inputs.** They exercise the listed axes and a few normal cases. They are not
  exhaustive, so agreement on them does not prove two implementations are equivalent.
- **Python only, US/English-centric** (dollars, US phone numbers, English title-case rules).
- **Contamination.** Several of these ambiguities (median of an even list, banker's rounding,
  slugify) are well-known, and models may have strong priors about them.
