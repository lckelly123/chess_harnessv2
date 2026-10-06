# First test-set queue summary

The model completed and received a grade on **183/200 positions (91.5%)**; **17 attempts failed (8.5%)**. Among graded moves, **50 were best/excellent (27.3%)**, while **87 were blunders (47.5%)**. This baseline shows substantial move-quality problems alongside tool-use failures.

Queue: `5c682038-872f-4f59-8352-2c854ca15733`  
Model: `unsloth/qwen3.8-27b` / harness: `agent-player-2-langgraph-v1`  
Run dates: September 23–24, 2026 (UTC). All results below are restricted to this queue; standalone runs are excluded.

| Move classification | Count | % of 183 graded moves |
| --- | ---: | ---: |
| Best | 30 | 16.4% |
| Excellent | 20 | 10.9% |
| Good | 12 | 6.6% |
| Inaccuracy | 19 | 10.4% |
| Mistake | 15 | 8.2% |
| Blunder | 87 | 47.5% |

Grades use **Stockfish 18**, native WDL, and `expected-points-v1`. Mean expected-points loss relative to the engine's best move was **0.286**; median loss was **0.163**. Mean CP loss was **190 cp**, with a median of **83 cp**, across 172 numeric CP results; 11 mate-score results are excluded from those CP statistics.

The set contained **120 middlegames, 40 openings, and 40 endgames**, with **160 quiet and 40 tactical positions**.

| Phase | Graded / attempted | Blunders / graded |
| --- | ---: | ---: |
| Opening | 39 / 40 | 17 / 39 (43.6%) |
| Middlegame | 108 / 120 | 55 / 108 (50.9%) |
| Endgame | 36 / 40 | 15 / 36 (41.7%) |

**Middlegames were the weakest segment**, also recording the highest mean expected-points loss (0.330, versus 0.242 in openings and 0.200 in endgames). These are comparisons across different positions, without difficulty adjustment. Tactical results were polarized: 20 best moves and 17 blunders among 37 graded attempts. Quiet positions produced 70 blunders among 146 graded attempts (47.9%).

The **17 run failures** were all execution failures: 10 exceeded the tool-call limit, three exhausted formatting/forced-tool retries, and four hit the rejected-tool limit. Of those four, the final rejection concerned a missing opponent reply in three runs and a nonexistent branch in one. There were no evaluation-stage failures.

**More activity did not imply better moves.** Blunder runs averaged 11.5 passes and 17.6 recorded tool calls, versus 8.0 passes and 12.2 calls for best/excellent runs. Failed-pass rates were similar: 22.7% versus 21.4%. Recorded calls include unsuccessful attempts. This supports focusing on the quality of candidate testing and interpretation of tool results, rather than simply increasing the call budget; these aggregate results alone do not establish the cause of individual blunders.
