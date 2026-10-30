# Evaluation results

## v0.2.0 (2026-10-30): eight full runs, including a re-run of the pre-refactor code

Every run used the same 32-spec benchmark and N=12 implementations per condition, live on Nebius Token Factory
(NVIDIA Nemotron 3.5 Lightning and NVIDIA Nemotron 3 Ultra). Intervals are 95% percentile bootstrap over items.
The raw JSON for each run is in [`docs/results/`](results/).

| Run | SpecFork configuration | SpecFork (ambiguous) | B1 ask-first | B0 none | SpecFork questions on clear specs |
|---|---|---|---|---|---|
| v1 (pre-refactor, `eval-20261030-144500`) | original pipeline | 41.9% | 39.0% | 21.0% | 2.00 |
| v2 (`v2-strict`) | strict assumptions (confidence ≥ 0.6, ≤ 2, witness required) | 21.8% | 38.6% | 24.0% | 0.83 |
| v3 (`v3-mid`) | confidence ≥ 0.3, ≤ 3 | 30.1% | 44.4% | 21.6% | 1.00 |
| v4 (`v4-defaults`) | restored defaults | 29.6% (15–46%) | 48.5% (31–66%) | 21.7% (9–36%) | 1.67 |
| v5 (`v5-freetext`) | defaults; the simulated owner may answer in free text | 29.8% (16–45%) | 42.3% (28–58%) | 21.2% (9–35%) | 2.67 |
| v6 (`v6-mixed`) | defaults + mixed fan-out (Nemotron 3.5 Lightning + Qwen3 30B) | **35.0%** (20–52%) | 46.0% (31–61%) | 19.9% (8–34%) | 2.33 |
| v1-rerun (`v1code-rerun`) | **the pre-refactor code (commit 78048a2), re-run today** | 30.8% | 48.8% | 22.4% | 1.83 |
| v7 (`v7-nojsonmode`) | defaults, JSON mode off for Lightning (ablation) | 33.1% (18–50%) | 49.2% (33–66%) | 18.0% (6–32%) | 2.60 |

**Pooled over the five runs with default settings** (v1, v1-rerun, v4, v5, v7; per-item means): SpecFork **33.1%**,
ask-first **45.7%**, no clarification **20.8%**.

What this shows, plainly:
- **The refactor did not cause the drop.** The exact pre-refactor code, re-run today, scores 30.8%, in the same
  range as the refactored code. Turning off the one suspicious change (JSON mode) gives 33.1%. The v1 figure of
  41.9% was a favourable single run, and the earlier "tie with ask-first" claim does not hold up.
- **SpecFork trails a well-prompted ask-first baseline by about 13 points on intent alignment.** Both clearly beat
  no clarification.
- **Why it loses.** SpecFork's questions are well chosen and backed by executed witnesses, but answers are limited
  to behaviours some sample produced, so intent the owner has but no sample showed gets lost:
  - `shipping_cost`: the witness covered negative weights; the owner meant "≤ 0 raises", so 0 kg kept a price.
  - `normalize_phone`: the closest available option contradicted the intent.

  The ask-first baseline lets the owner state rules in their own words. Where the deciding behaviour only shows up
  when code runs, SpecFork wins clearly (`page_count` +42 points, `cart_discounts` +25 over ask-first).
- **Assumption calibration is a real trade-off.** Fewer questions on clear specs (2.0 → 0.83) came with lower
  accuracy on ambiguous specs. Defaults favour recall. The review's target (≤ 0.5 false-alarm questions with no
  alignment loss) is **not met**.
- **Free-text "Other…" answers** were used in 4 of 26 items without moving the metric.
- **Mixed-model fan-out** (35.0%) was the best configuration in one run. Treat it
  as a lead.
- **What only SpecFork produces:** an executed witness for every question, deterministic locked tests, and a
  measured re-fork.

### Attempted fix: open questions (opt-in, `SPECFORK_OPEN_QUESTIONS=1`)

After the witness questions, SpecFork also asks up to 3 "anything else?" questions the executed evidence did not
cover, answered in the owner's own words. The deep model then implements the full clarified spec and the result is
executed. Each run below has 2 repeats per item; the 95% intervals are over items.

| Run | Open-question prompt | SpecFork (ambiguous) | B1 ask-first | SpecFork on clear specs (alignment / questions) |
|---|---|---|---|---|
| v8 (`v8-openq-broad-x2`) | broad (also asks about validation and error handling) | **41.6%** (29–55%) | 49.1% (34–65%) | 87.5% / 2.17 |
| v9 (`v9-openq-tight-x2`) | tight (only realistic, behaviour-changing questions) | 32.2% (19–47%) | 46.8% (32–61%) | 98.6% / 1.92 |

**Result: not a clean fix.**
- The broad version lifts ambiguous-spec accuracy by about 8 points over the pooled default (33.1%), closing roughly
  half the gap to ask-first. But on clear specs the simulated owner over-specifies, and alignment drops to 87.5%.
- The tight version keeps clear specs correct but loses the gain.
- Open questions therefore stay **off by default**.
- The likely way forward is to let the owner add a free-text refinement to every chosen option, rather than adding
  separate questions. That is tracked in the roadmap.

---

## v0.1.0 (pre-refactor) report

**Status: executed** on 2026-10-30, live against Nebius Token Factory (`nvidia/Nemotron-3_5-Lightning` and `nvidia/Nemotron-3-Ultra-550b-a55b`).
Raw results: [`docs/results/eval-20261030-144500.json`](results/eval-20261030-144500.json). Reproduce with `make eval` (`evals/run_eval.py --n 12`).

## Setup
- **Benchmark:** 32 hand-written function specs ([`evals/benchmark/`](../evals/benchmark/README.md)).
  - 26 are ambiguous, with 52 labelled ambiguity axes. 6 are clear controls.
  - Each spec has a hidden *intent* and a hidden reference implementation, tested on 10–20 hidden inputs.
  - No model ever sees the hidden inputs or the reference.
- **Conditions:** all use the same fixed signature, the same fast model, and N=12 implementations per condition.
  - **B0, no clarification:** implement the original spec as written.
  - **B1, ask-first:** one Lightning call (reasoning on) lists up to 5 clarifying questions. A simulated product owner (Lightning, given the hidden intent) answers them in free text. Ultra rewrites the spec. Then N implementations.
  - **SF, SpecFork:** the full pipeline (fan-out, execution, clustering, witness questions and silent-assumption questions). The simulated owner picks options, restricted to options consistent with its earlier answers. SpecFork resolves the spec, then re-forks N implementations.
- **Metric (intent alignment):** the share of executed implementations that match the hidden reference on all hidden inputs. Canonical comparison; any exception matches "raises".

## Results
Implementations per condition per item: N=12

| Condition | Spec set | Items | Mean intent alignment | Items >50% aligned | Items 100% aligned | Mean questions | Cost (USD) |
|---|---|---|---|---|---|---|---|
| B0 no clarification | ambiguous | 26 | 21.0% | 5 | 3 | 0.00 | $0.0135 |
| B1 ask-first (no execution) | ambiguous | 26 | 39.0% | 11 | 6 | 3.77 | $0.0595 |
| SpecFork | ambiguous | 26 | 41.9% | 11 | 4 | 3.31 | $0.3910 |
| B0 no clarification | control | 6 | 100.0% | 6 | 6 | 0.00 | $0.0021 |
| B1 ask-first (no execution) | control | 6 | 100.0% | 6 | 6 | 0.33 | $0.0070 |
| SpecFork | control | 6 | 98.6% | 6 | 5 | 2.00 | $0.0527 |

SpecFork chosen behaviour matched the hidden reference on all hidden inputs in 6/26 ambiguous items.


**Per-item head-to-head (ambiguous specs):** SpecFork beat B1 on 8 items, B1 beat SpecFork on 9, and the rest tied.

## Honest reading
- **Clarifying helps.** Both clarification approaches roughly double intent alignment over no clarification (21.0% to about 40%).
- **SpecFork vs. B1 is a tie.** SpecFork scores 41.9% and B1 39.0%. That is one run of 26 items, and the difference is within noise. **We do not claim SpecFork beats a well-prompted ask-first baseline on alignment.**
- **Where SpecFork wins:**
  - A behavioural disagreement exposes a decision a list of questions misses (`page_count`, `cart_discounts`: 12/12 vs 0/12).
  - Its silent-assumption review catches a shared default (`letter_grade` on the 6-item development subset).
- **Where SpecFork loses:**
  - The owner's intent is a behaviour **no sampled implementation produced** (`moving_average`, `split_full_name`, `shift_length`). Options can only choose among executed behaviours plus model-proposed alternatives. B1's free-text answers can describe anything.
  - A free-text "other…" answer is the obvious next step.
- **False alarms:** on the 6 controls, SpecFork asked about 2 assumption questions per spec (B1: 0.33), while keeping 98.6% alignment. The assumption review is too eager on simple specs.
- **Cost and latency:** SpecFork costs about $0.015 per spec, against about $0.002 for B1 and about $0.0005 for B0. A full SpecFork run takes 1–2 minutes in this harness.
- **What only SpecFork produces:**
  - every question comes with an **executed witness** (a real input and the real outputs);
  - a **deterministic pytest file** locked from executed behaviour;
  - a **measured** re-fork agreement.
  - B1 produces none of these. These benefits are structural and are not captured by the alignment metric.

## Development history (disclosed)
- The pipeline was tuned on live runs today. An 8-item subset (`truncate_preview, percent_change, parse_slash_date, top_k_ties, bill_split, business_days, median, letter_grade`) was used repeatedly during development, so those items are not held out.
- Changes made during development:
  - the decision-only clarifier;
  - compatible-answer selection;
  - silent-assumption questions;
  - the likely-bug guard.
- An earlier full run with an older clarifier was aborted part-way. Its partial numbers were worse for SpecFork and are not reported as final.
- The 6-item development check right before the full run scored SF 60.4%, B1 47.6%, B0 15.8%. That was on development items, so it is optimistic.

## Limitations
- The benchmark is small and author-written, so it may be biased. Some intended answers are deliberately unpopular conventions.
- The product owner is simulated by an LLM.
- One run with N=12 per condition; no confidence intervals.

## Per-item results (aligned/executed; q = questions asked)
| item | set | axes | B0 | B1 | SpecFork |
|---|---|---|---|---|---|
| age_on_date | amb | 2 | 0/12 | 0/12 (0q) | 2/11 (5q, 3 assumpt.) |
| bill_split | amb | 1 | 0/10 | 0/12 (5q) | 9/11 (4q, 3 assumpt.) |
| business_days | amb | 2 | 5/11 | 6/12 (3q) | 6/11 (3q, 1 assumpt.) |
| cart_discounts | amb | 2 | 0/12 | 0/12 (5q) | 12/12 (4q, 3 assumpt.) |
| currency_format | amb | 2 | 0/12 | 0/10 (4q) | 0/12 (3q, 3 assumpt.) |
| email_dedupe | amb | 3 | 0/12 | 12/12 (5q) | 3/12 (3q, 3 assumpt.) |
| human_file_size | amb | 3 | 1/12 | 7/12 (5q) | 4/12 (5q, 3 assumpt.) |
| letter_grade | amb | 2 | 0/12 | 0/12 (0q) | 0/12 (3q, 3 assumpt.) |
| median | amb | 2 | 11/11 | 9/9 (5q) | 11/11 (3q, 3 assumpt.) |
| merge_intervals | amb | 1 | 12/12 | 12/12 (5q) | 10/11 (0q, 0 assumpt.) |
| moving_average | amb | 2 | 0/12 | 8/12 (5q) | 0/12 (4q, 3 assumpt.) |
| normalize_phone | amb | 2 | 0/12 | 1/12 (5q) | 2/10 (6q, 3 assumpt.) |
| page_count | amb | 1 | 0/12 | 0/12 (0q) | 12/12 (3q, 2 assumpt.) |
| parse_slash_date | amb | 2 | 0/12 | 8/12 (4q) | 0/12 (0q, 0 assumpt.) |
| password_strength | amb | 2 | 8/12 | 0/12 (5q) | 8/12 (5q, 3 assumpt.) |
| percent_change | amb | 2 | 0/12 | 0/12 (0q) | 0/10 (2q, 2 assumpt.) |
| round_temperature | amb | 2 | 0/12 | 7/12 (1q) | 5/11 (4q, 3 assumpt.) |
| shift_length | amb | 2 | 0/12 | 12/12 (5q) | 9/12 (3q, 2 assumpt.) |
| shipping_cost | amb | 2 | 0/12 | 0/12 (3q) | 0/12 (3q, 3 assumpt.) |
| slugify | amb | 2 | 0/12 | 0/12 (5q) | 0/12 (4q, 3 assumpt.) |
| split_full_name | amb | 2 | 2/12 | 3/12 (5q) | 0/12 (4q, 3 assumpt.) |
| title_case | amb | 3 | 0/12 | 3/11 (5q) | 4/12 (5q, 2 assumpt.) |
| top_k_ties | amb | 2 | 9/12 | 12/12 (5q) | 12/12 (3q, 3 assumpt.) |
| truncate_preview | amb | 2 | 12/12 | 12/12 (3q) | 11/12 (3q, 2 assumpt.) |
| week_number | amb | 1 | 4/12 | 6/11 (5q) | 6/11 (0q, 0 assumpt.) |
| word_count | amb | 3 | 0/12 | 0/10 (5q) | 0/11 (4q, 3 assumpt.) |
| ctrl_c_to_f | ctrl | 0 | 12/12 | 11/11 (0q) | 11/11 (3q, 3 assumpt.) |
| ctrl_count_char | ctrl | 0 | 12/12 | 12/12 (0q) | 12/12 (1q, 0 assumpt.) |
| ctrl_fizzbuzz | ctrl | 0 | 11/11 | 12/12 (2q) | 11/11 (1q, 1 assumpt.) |
| ctrl_leap_year | ctrl | 0 | 12/12 | 12/12 (0q) | 12/12 (2q, 2 assumpt.) |
| ctrl_reverse_words | ctrl | 0 | 12/12 | 12/12 (0q) | 11/12 (2q, 1 assumpt.) |
| ctrl_sum_ints | ctrl | 0 | 12/12 | 12/12 (0q) | 12/12 (3q, 3 assumpt.) |
