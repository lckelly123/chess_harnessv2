# First Training Set Results

**Run:** `train_set_test1.0_10/10/26`  
**Model:** Qwen3-14B via Unsloth · **Harness:** chess_harness · **Dataset:** v1/train  
**Finished:** October 11, 2026, 12:19 a.m. PDT — all 200 positions attempted.

## Overall

- **Graded moves:** 167/200 (**83.5%**).
- **Failed attempts:** 33/200 (**16.5%**).
- **Average time:** 1.9 minutes per position; 6 hours 24 minutes total.
- **Model passes:** 2,849; average **14.2 per position**. Forced retries: **43 (1.5%)**.

## Move quality

Percentages are of the **167 graded moves**; failed attempts are excluded.

| Quality | Moves | Percentage |
|---|---:|---:|
| Best | 13 | 7.8% |
| Excellent | 21 | 12.6% |
| Good | 18 | 10.8% |
| Inaccuracy | 12 | 7.2% |
| Mistake | 14 | 8.4% |
| Blunder | 89 | 53.3% |

Average engine expected-point loss: **0.349** (lower is better).

## Tool usage

Percentages are of **6,319 recorded tool requests**, including requests that did not execute.

| Tool | Requests | Percentage |
|---|---:|---:|
| `annotate_branch` | 2,354 | 37.3% |
| `inspect_square` | 1,971 | 31.2% |
| `scratch_play_move` | 1,620 | 25.6% |
| `scratch_reset` | 202 | 3.2% |
| `submit_move` | 170 | 2.7% |
| `scratch_undo` | 2 | <0.1% |

**6,218 requests executed (98.4%).** Of those, **320 returned errors (5.1%)**.

## Failure reasons

Percentages are of the **33 failed attempts**, grouped by the final recorded error.

- Scratchboard depth limit: **18 (54.5%)**.
- Missing branch references: **10 (30.3%)**.
- Illegal moves: **2 (6.1%)**.
- Protocol/forced-retry limit: **3 (9.1%)**.

These results use the training split; comparison with the Test Set 1.0 report involves different positions.

Source queue: `22e0cf5c-8ba2-4459-bcf9-4ce9cf4480ae`. Percentages rounded.
