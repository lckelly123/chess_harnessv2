# Test Set 1.0 Report

**Run:** `Qwen_14B_testset_10`  
**Model:** Qwen3-14B · **Harness:** Agent Player 2 · **Dataset:** v1/test  
**Finished:** October 7, 2026, 3:54 p.m. PDT — all 200 positions attempted.

## Overall

- **Graded moves:** 72/200 (**36.0%**).
- **Failed attempts:** 128/200 (**64.0%**).
- **Average time:** 4.9 minutes per position; 16 hours 28 minutes total.
- **Model passes:** 3,722; average **18.6 per position**. Forced retries: **610 (16.4%)**.

## Move quality

Percentages are of the **72 graded moves**; failed attempts are excluded.

| Quality | Moves | Percentage |
|---|---:|---:|
| Best | 11 | 15.3% |
| Excellent | 9 | 12.5% |
| Good | 3 | 4.2% |
| Inaccuracy | 4 | 5.6% |
| Mistake | 6 | 8.3% |
| Blunder | 39 | 54.2% |

Average engine expected-point loss: **0.368** (lower is better).

## Tool usage

Percentages are of **5,150 recorded tool requests**, including requests that did not execute.

| Tool | Requests | Percentage |
|---|---:|---:|
| `inspect_square` | 3,017 | 58.6% |
| `scratch_play_move` | 1,220 | 23.7% |
| `annotate_branch` | 579 | 11.2% |
| `submit_move` | 249 | 4.8% |
| `scratch_reset` | 84 | 1.6% |
| `scratch_undo` | 1 | <0.1% |

**3,806 requests executed (73.9%).** Of those, **421 returned errors (11.1%)**.

## Failure reasons

Percentages are of the **128 failed attempts**.

- Illegal moves: **48 (37.5%)**.
- Tool-call budget exhausted: **44 (34.4%)**.
- Branch management/submission errors: **33 (25.8%)**.
- Protocol/forced-retry limit: **3 (2.3%)**.

Source queue: `cfe985c8-f8df-4188-94a4-8362f0cd5246`. Percentages rounded.
