# Training Set 2.2 Results

**Run:** `true_trial_v1.2`  
**Model:** Qwen3-14B via Unsloth · **Harness:** chess_harness · **Dataset:** v1/test  
**Checkpoint:** `Qwen_Qwen3-14B__project-true_trial_v1.2_1792377947`  
**Stopped:** October 20, 2026, 12:30 p.m. PDT — **40/200 positions attempted**, 160 skipped.

## Overall

Completion and failure rates use the **40 attempted positions**; skipped positions are excluded.

- **Graded moves:** 21/40 (**52.5%**).
- **Failed attempts:** 19/40 (**47.5%**).
- **Average time:** 16.5 minutes per attempted position; 10 hours 58 minutes total.
- **Model passes:** 685; average **17.1 per attempted position**. Forced retries: **5 (0.7%)**.

## Move quality

Percentages are of the **21 graded moves**; failed attempts are excluded.

| Quality | Moves | Percentage |
|---|---:|---:|
| Best | 4 | 19.0% |
| Excellent | 1 | 4.8% |
| Good | 3 | 14.3% |
| Inaccuracy | 4 | 19.0% |
| Mistake | 1 | 4.8% |
| Blunder | 8 | 38.1% |

Average engine expected-point loss: **0.323** (lower is better).

## Tool usage

Percentages are of **1,726 recorded tool requests**, including requests that did not execute.

| Tool | Requests | Percentage |
|---|---:|---:|
| `annotate_branch` | 930 | 53.9% |
| `scratch_play_move` | 458 | 26.5% |
| `inspect_square` | 209 | 12.1% |
| `scratch_reset` | 87 | 5.0% |
| `scratch_undo` | 21 | 1.2% |
| `submit_move` | 21 | 1.2% |

**1,709 requests reached tool execution (99.0%).** Of those, **150 had recorded errors (8.8%)**. Execution counts include rolled-back batches.

## Failure reasons

Percentages are of the **19 failed attempts**, grouped by the final recorded error.

- Illegal moves: **14 (73.7%)**.
- Scratchboard depth limit: **4 (21.1%)**.
- Protocol/forced-retry limit: **1 (5.3%)**.

These are partial results from the first 40 scheduled test positions, not a full-set result. The First Training Set Results report uses different positions from the training split.

Source queue: `79875e8b-fcb1-488f-ae54-78d63ae046e9`. Snapshot: October 20, 2026, 1:05 p.m. PDT, before any retries. Percentages rounded.
