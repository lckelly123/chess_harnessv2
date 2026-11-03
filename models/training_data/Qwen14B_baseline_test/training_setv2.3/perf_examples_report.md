# Perf Examples Results

**Run:** `perf_examples`  
**Model:** GPT-6 Astra (`gpt-6-astra`), extra-high reasoning · **Mode:** Codex (training)  
**Harness:** chess_harness · **Dataset:** v1/train  
**Status:** Stopped — **187/199 retained positions attempted**, 12 skipped.

## Overall

Rates use the **187 attempted positions**, taking the latest retained attempt per position after queue retries. Skipped and discarded attempts are excluded. Earlier superseded entries (**256 failed, 601 skipped**) are also excluded from all totals below.

- **Graded moves:** 181/187 (**96.8%**).
- **Failed attempts:** 6/187 (**3.2%**).
- **Average time:** 21.1 minutes per attempted position; 65 hours 50 minutes of recorded attempt time.
- **Model passes:** 3,566; average **19.1 per attempted position**. Forced retries: **14 (0.4%)**.

## Move quality

Percentages are of the **181 graded moves**; failed attempts are excluded.

| Quality | Moves | Percentage |
|---|---:|---:|
| Best | 65 | 35.9% |
| Excellent | 37 | 20.4% |
| Good | 17 | 9.4% |
| Inaccuracy | 5 | 2.8% |
| Mistake | 18 | 9.9% |
| Blunder | 39 | 21.5% |

Average engine expected-point loss: **0.123** (lower is better).

**119 moves were good or better (65.7%).** These positions supplied the **2,132 training rows** in `train_2.3_full.jsonl`, after omitting eight rejected responses and their eight forced-retry passes.

## Tool usage

Percentages are of **10,118 recorded tool requests**, including requests that did not execute.

| Tool | Requests | Percentage |
|---|---:|---:|
| `annotate_branch` | 5,829 | 57.6% |
| `scratch_play_move` | 2,245 | 22.2% |
| `inspect_square` | 1,293 | 12.8% |
| `scratch_reset` | 383 | 3.8% |
| `submit_move` | 186 | 1.8% |
| `scratch_undo` | 182 | 1.8% |

**10,062 requests reached tool execution (99.4%).** Of those, **0 had recorded errors (0.0%)**. The remaining 56 requests did not execute. Separately, **14 responses were rejected for annotations exceeding 600 characters**, triggering forced retries.

## Failure reasons

Percentages are of the **6 failed attempts**, grouped by the final recorded error.

- Codex model at capacity: **4 (66.7%)**.
- Position exceeded the 5,000-second limit: **2 (33.3%)**.

These results cover the teacher queue on the training split. The neighboring v2.3 results report evaluates the trained Qwen model on the test split.

Source queue: `bd73f388-8a83-4edc-afa2-f96ab192b200`. Snapshot: October 28, 2026, 11:35 p.m. PDT. Percentages rounded.
