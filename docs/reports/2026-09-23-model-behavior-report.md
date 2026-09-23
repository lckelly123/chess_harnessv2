# Model behavior across better and worse moves

Snapshot: **September 23, 2026, 1:40:32 p.m. PDT / 20:40:32 UTC**. Database access was read-only. No prompts, application logic, grades, or database rows were changed.

**The strongest observed distinction is how the model responds to adverse evidence.** Useful passes recognize a refutation, preserve it in notes and annotations, and change candidates. Weak passes claim that rejected or unplayed continuations were tested, retain favorable but contradicted annotations, or redefine a known loss as merely unresolved. Tool volume and note length, by themselves, have almost no relationship with numerical centipawn loss in this sample.

This report compares behavior associated with different outcomes. It does **not** establish that the model improved or deteriorated over time: the runs concern different positions, not repeated controlled trials of the same positions.

**Scope and scoring**

The snapshot contains 122 runs. The main comparison uses **109 graded runs on 109 distinct positions**, all from `unsloth/qwen3.8-27b` and `agent-player-2-langgraph-v1`, with the same recorded model settings. They contain **1,125 model passes**. Of these graded runs, 108 belong to the test queue and one is a manual training-position run. Eleven failed Agent Player 2 runs and one active run are analyzed separately; an earlier ungraded Agent Player 3 run is excluded.

The test queue was still running: 108 completed, 11 failed, one running, and 80 queued. The comparison is therefore a fixed, partial snapshot of the 200-position queue.

All grades use Stockfish 18 and the same `expected-points-v1` policy. Two outcome measures are kept separate:

- **Classification** uses expected-points loss: excellent below 0.02, good 0.02–<0.05, inaccuracy 0.05–<0.10, mistake 0.10–<0.20, and blunder at least 0.20. Best additionally requires zero expected-points loss and a score equal to the top candidate.
- **CP loss** is the stored engine score difference between the best candidate and the chosen move, from the agent's perspective. It is available for 104 runs. Five runs involve mate scores and have no numerical CP loss; they are excluded from numerical CP statistics, not counted as zero.

This engine CP loss is different from the scratchboard's **material CP**, which is static piece-value accounting. A material deficit may have compensation; claiming that compensation requires evidence.

**Outcome and behavior overview**

Successful tools below means calls whose results committed. Rejected calls and calls rolled back with a failed batch are excluded. Pass failure rates include formatting/retry failures as well as rejected-tool passes.

| Classification | Runs | Numeric CP sample | Median / mean CP loss | Mean passes | Mean successful tools | Failed passes |
|---|---:|---:|---:|---:|---:|---:|
| Best | 17 | 13 | 0 / 0 | 7.8 | 10.1 | 24.1% |
| Excellent | 9 | 9 | 17 / 52 | 8.7 | 11.8 | 19.2% |
| Good | 9 | 9 | 42 / 53 | 11.0 | 14.4 | 20.2% |
| Inaccuracy | 12 | 12 | 48.5 / 108 | 10.4 | 14.2 | 19.2% |
| Mistake | 10 | 10 | 98 / 117 | 10.0 | 12.3 | 27.0% |
| Blunder | 52 | 51 | 262 / 339 | 11.3 | 14.6 | 23.7% |

Best/excellent runs average fewer calls than blunders, but that is not a smooth relationship across the six classes. The best group also contains four immediate checkmates. Position mix differs: 15/26 best/excellent positions are quiet, compared with 43/52 blunders.

Classification and CP loss can disagree without either field being broken. Queue 106 is **excellent despite 179 CP loss**, because expected points fall from 0.0195 to zero in an already nearly lost position. Queue 18 is an **inaccuracy despite 480 CP loss**, with expected-points loss 0.056. Conversely, the smallest numerical CP loss labeled blunder is 44. Selecting training passes by classification alone would overlook these distinctions.

**Tool quantity does not distinguish low and high CP loss**

| Stored CP loss | Runs | Mean passes | Mean successful tools | Mean inspections | Mean distinct root candidates |
|---|---:|---:|---:|---:|---:|
| 0–20 | 21 | 9.8 | 12.6 | 3.0 | 1.33 |
| 21–100 | 32 | 11.3 | 14.5 | 2.7 | 1.56 |
| 101–300 | 24 | 11.0 | 14.3 | 3.8 | 1.38 |
| Above 300 | 27 | 10.2 | 13.3 | 2.6 | 1.59 |

Among the 104 numerical-CP runs, descriptive Spearman rank correlations with CP loss are **−0.067 for pass count, −0.042 for successful tools, −0.026 for inspections, and +0.035 for average normal-pass note length**. These are near zero. They do not establish causality or statistical equivalence, but they give no useful simple rule such as “more tools means a better move.”

The best/excellent versus blunder tool mix also overlaps substantially:

| Successful calls per run | Best/excellent | Blunder |
|---|---:|---:|
| Scratch moves | 3.31 | 4.71 |
| Branch annotations | 3.46 | 5.15 |
| Square inspections | 2.58 | 2.87 |
| Distinct initial candidates | 1.23 | 1.62 |

Blunders contain more activity, but much of it is annotation and additional analysis of a small candidate set. Restricting the comparison to quiet positions leaves the same broad result: best/excellent averages 12.2 successful tools versus 15.0 for blunders, while inspections are virtually identical, 3.07 versus 3.02. More inspection is not enough if the conclusion ignores its result.

**Opponent testing is narrow, but reply selection is only part of the problem**

Seventy of 109 runs test just one root candidate. Among 105 runs whose selected move is not an immediate terminal mate, **101 test only one immediate opponent reply**. Only four test two replies to the selected move. None of the 52 blunders scratch-tests the engine's best root move as an alternative; this shows missing candidate coverage, rather than the engine move being tested and rejected.

As a limited quality check, I compared the tested reply with the first opponent move in the stored engine continuation:

- Best/excellent: **11/22 eligible runs, 50.0%**.
- Blunder: **16/52 runs, 30.8%**.
- Across all classes: **37/105 runs, 35.2%**.

This aggregate difference is strongly sensitive to position mix. For **quiet positions alone**, the rates are **4/15 best/excellent, 26.7%, versus 13/43 blunders, 30.2%**. There is no corresponding advantage in that subset. Matching one engine line is also an imperfect measure: unmatched replies may be equally strong.

The trace evidence supports two separate failure mechanisms: choosing a cooperative opponent reply, and finding a strong reply but failing to accept its consequences. Queue 44 illustrates the first: after Qxb2+, it calls Kd1 the only reply even though Kxb2 legally captures its queen; the move loses **622 CP**. Queue 90 illustrates the second: it tests the engine's immediate Nxf7 reply, recognizes the pawn loss, and still submits g6 with **205 CP loss**.

**Working-note usage: evidence retention matters more than length**

The prompt requests a full replacement of Vulnerabilities, Opportunities, and Synthesis on every pass. Repetition is therefore partly expected, especially on forced retries.

| Working-note measure | Best/excellent | Blunder |
|---|---:|---:|
| Mean characters per normal pass, averaging runs equally | 970 | 1,011 |
| Mean final-note characters | 1,062 | 1,107 |
| Notes identical to preceding pass, after whitespace normalization | 56/185, 30.3% | 142/538, 26.4% |

Neither longer notes nor less verbatim repetition clearly identifies better decisions. Exact repetition is only a copying measure; it does not detect paraphrased repetition or prove that a pass added useful analysis. One hundred of 1,125 passes commit annotations without another successful tool type, but annotation-only work is not inherently wasteful: repairing a false branch conclusion can be important.

The qualitative difference appears in the relationship between the notes and recorded evidence:

| More useful behavior in reviewed passes | Less useful behavior in reviewed passes |
|---|---|
| Names the actual attacker, captured piece, and remaining uncertainty | Uses generic pressure or development claims to excuse a concrete loss |
| Keeps a refuted candidate rejected across later passes and retries | Gradually relabels an established loss as “unverified,” then acceptable |
| Corrects both current notes and persistent branch annotations | Corrects prose while favorable stale annotations remain |
| Calls an unplayed continuation a proposal | Calls an imagined or rejected continuation a scratch test |
| Tests the next opponent resource after a temporary gain | Stops when one chosen opponent continuation gives a favorable result |

These are verified examples of mechanisms, not automated prevalence labels for every run.

**Examples spanning all six classifications**

The following recent runs provide more useful comparisons than treating all best/excellent transcripts as good demonstrations. Queue numbers refer to the same active test queue. Full UUIDs, exact excerpts, and replay details are in the [evidence appendix](C:/Repos/chess_harness_v2/chess_harnessv2/docs/reports/2026-09-23-model-behavior-evidence.md).

| Queue | Move | Class | CP loss | What changes in the model's behavior |
|---|---|---|---:|---|
| 103 | Bd3 | Best | 0 | Accepts the adverse e4 dxe4 result, switches candidates, and corrects an illegal Qb6 claim in both working notes and annotation at pass 13. |
| 87 | Rc2 | Excellent | 53 | Replaces a false Rxc8+ annotation after realizing its own c7 pawn blocks the rook. The correction is real; the favorable class partly reflects an already losing position. |
| 83 | Nf6 | Good | 9 | Rejects d5 after the played line loses a knight, preserves that conclusion through a retry, and switches to development. Final opponent coverage remains incomplete. |
| 84 | Nxe3 | Inaccuracy | 87 | Calls Qe2 a stronger reply that “was then tested,” although its only attempted Qe2 call was rejected and never successfully replayed. Repeated inspections do not repair that false memory. |
| 90 | g6 | Mistake | 205 | Finds the engine's immediate reply, Nxf7, but keeps the candidate despite the pawn loss. Some attempted annotation repairs roll back; old recovery claims remain. |
| 118 | Qxe1+ | Blunder | 381 | Correctly labels Qxe1+ Qxe1 a −400-material-CP refutation, then overwrites it as “Unverified as refutation” without testing a recovery and submits the move. |

Queue 118 is particularly informative. At pass 10 it writes that the candidate is refuted because it loses a queen for a rook without demonstrated compensation. At pass 12 it retracts that conclusion because possible follow-up tactics have not been tested. No successful continuation of that branch supplies new evidence. Pass 13 submits anyway. Here, the failure is not missing the opponent's capture: **the model observed the loss and weakened its own acceptance criterion**.

Queue 15 remains a useful positive segment: passes 6–10 execute Qxd3 Qxh2+ Kxh2 exd3, matching the stored engine line for all four halfmoves. It does not stop after capturing the opponent queen; it checks the opponent's subsequent capture of its own queen. Its final move loses zero CP. Earlier passes are less reliable, so this supports selecting individual verified passes rather than endorsing the whole transcript.

**Failures and forced retries do not cleanly separate move quality**

There are **258 failed passes out of 1,125, or 22.9%**, within runs that ultimately receive grades. These comprise 209 format/retry failures and 49 rejected-tool passes. The main format issues are missing tool-call blocks (135), multiple board mutations in one batch (50), and missing working-note blocks (15). Some reasoning-only responses trigger retries without incrementing the harness's internal protocol-error counter; “format/retry failures” is therefore the appropriate report label.

Best/excellent has **47/211 failed passes, 22.3%**, versus **140/590, 23.7%** for blunders. These similar rates do not support retry frequency as the primary separator of final quality.

Reconstructing the current control flow suggests 220 passes ran in forced mode. Final submissions occur in inferred forced mode in **15/26 best/excellent runs and 29/52 blunders**, approximately 58% and 56%. These are inferred counts: the event table does not persist an explicit forced flag or exact prompt. Forced mode can preserve an already mistaken conclusion, but the data do not show that it uniquely causes blunders.

The **11 fully failed queue runs** have no move grade and must remain outside the CP comparisons. Seven hit the tool-call limit, three exhaust forced retries, and one reaches the rejected-tool limit. That is **11/119 finished queue attempts, 9.2%**, at this snapshot. They remain a separate reliability problem even if move selection improves.

**Harness and measurement checks**

I independently replayed all **460 committed scratch moves** and checked all **319 successful square-inspection occupants** in the graded cohort. There were no substantive board-state or occupant mismatches. Four raw FEN differences involved irrelevant en-passant target serialization; legally normalized board states matched. This checks state transport and move execution, not every attack-map calculation or all harness semantics.

The 1,536 attempted calls reconcile to **1,458 committed successes, 49 direct rejections, and 29 rolled-back calls**. Successful calls comprise 501 annotations, 460 moves, 319 inspections, 109 submissions, 62 resets, and seven undos. Parsed-but-unexecuted requests are not counted as successful activity. Execution order is taken from the recorded execution-order field.

The current prompt already requires the strongest credible opponent reply, accurate material accounting, and correction of contradicted notes. The mechanical submission check requires a terminal candidate or at least one opponent reply; it cannot validate the strength of that reply or the truth of an annotation. The observed model errors often violate existing instructions rather than expose a missing instruction.

These conclusions are limited by different position difficulties, small intermediate-class samples, a partial queue, and the absence of saved exact prompts and explicit forced-pass flags. No full-pass semantic correctness rate is claimed. Recorded run settings match, but a shared prompt-version string alone does not prove byte-identical historical prompts. Run duration is not used as an inference-speed metric because it includes post-run Stockfish evaluation.

**Implications for selecting training passes**

Use classification and CP loss as separate outcome filters, then inspect each proposed target pass. The strongest demonstrated training behaviors are accepting a refutation, preserving it across retries, correcting both notes and annotations, and selecting a credible next opponent move. Avoid rewarding extra calls, long notes, the word “verified,” or a favorable final class by themselves.

A correct pass from a worse run can be useful; a false explanation from a best run remains a poor target. Also, most examples here come from the test queue. They can guide the behavioral rubric, but using them for training would remove those positions from the held-out evaluation set.

**Reproducibility and supporting files**

- [Run-level metrics CSV](C:/Repos/chess_harness_v2/chess_harnessv2/docs/reports/2026-09-23-model-behavior-metrics.csv): all 122 snapshot runs, including explicit ungraded/failed statuses.
- [Detailed case evidence](C:/Repos/chess_harness_v2/chess_harnessv2/docs/reports/2026-09-23-model-behavior-evidence.md): six-class examples, full run IDs, pass references, and verified continuations.
- [Frozen local database export](C:/Repos/chess_harness_v2/chess_harnessv2/backend/.test-data/behavior-review-2026-09-23-snapshot.json), [analysis script](C:/Repos/chess_harness_v2/chess_harnessv2/backend/.test-data/analyze_behavior_report.py), and [aggregate metrics](C:/Repos/chess_harness_v2/chess_harnessv2/backend/.test-data/behavior-review-2026-09-23-metrics.json).
- Definitions: [evaluation policy](C:/Repos/chess_harness_v2/chess_harnessv2/backend/positional_testing/evaluation.py:46), [pass recording](C:/Repos/chess_harness_v2/chess_harnessv2/backend/positional_testing/recording.py:102), [reply-verification instruction](C:/Repos/chess_harness_v2/chess_harnessv2/backend/harness/agent_player_2/prompt_builder/input_sections/synthesis/system/phase_instructions.md:138), and [minimum submission gate](C:/Repos/chess_harness_v2/chess_harnessv2/backend/harness/agent_player_2/tested_lines.py:119).
