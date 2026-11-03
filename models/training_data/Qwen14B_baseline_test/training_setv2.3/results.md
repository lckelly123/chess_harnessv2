# Training Set 2.3 Results

**Run:** `2.3_test`  
**Model:** Qwen3-14B via Unsloth · **Harness:** chess_harness · **Dataset:** v1/test  
**Checkpoint:** `Qwen_Qwen3-14B__project-true_trial_v1.2_1792812112`  
**Stopped:** October 27, 2026, 7:28 p.m. PDT — **31/199 retained positions attempted**, 168 skipped.

## Overall

Completion and failure rates use the **31 attempted positions**; skipped and discarded attempts are excluded.

- **Graded moves:** 19/31 (**61.3%**).
- **Failed attempts:** 12/31 (**38.7%**).
- **Average time:** 36.9 minutes per attempted position; 19 hours 3 minutes of recorded attempt time.
- **Model passes:** 781; average **25.2 per attempted position**. Same-input retries: **68 (8.7%)**.

## Move quality

Percentages are of the **19 graded moves**; failed attempts are excluded.

| Quality | Moves | Percentage |
|---|---:|---:|
| Best | 4 | 21.1% |
| Excellent | 1 | 5.3% |
| Good | 0 | 0.0% |
| Inaccuracy | 2 | 10.5% |
| Mistake | 3 | 15.8% |
| Blunder | 9 | 47.4% |

Average engine expected-point loss: **0.279** (lower is better).

## Tool usage

Percentages are of **2,051 recorded tool requests**, including requests that did not execute.

| Tool | Requests | Percentage |
|---|---:|---:|
| `annotate_branch` | 1,173 | 57.2% |
| `scratch_play_move` | 526 | 25.6% |
| `inspect_square` | 207 | 10.1% |
| `scratch_reset` | 89 | 4.3% |
| `scratch_undo` | 36 | 1.8% |
| `submit_move` | 20 | 1.0% |

**1,909 requests reached tool execution (93.1%).** Of those, **0 had recorded errors (0.0%)**. The remaining 142 requests did not execute; 51 had recorded rejection errors. Under the new retry policy, rejected batches execute no tools and retry with the same input.

## Failure reasons

Percentages are of the **12 failed attempts**, grouped by the final recorded error.

- Unsloth request timeout: **7 (58.3%)**.
- Position exceeded the 5,000-second limit: **2 (16.7%)**.
- Illegal scratchboard moves exhausted 10 same-input retries: **2 (16.7%)**.
- Unsloth server error (HTTP 500): **1 (8.3%)**.

These are partial results from 31 retained test positions, not a full-set result. Retry and tool-error rates reflect the new retry policy and are not directly comparable with v2.2.

Source queue: `8d9c2952-9bc7-4db6-9764-67076d89d0f3`. Snapshot: October 27, 2026, 7:31 p.m. PDT. Percentages rounded.
