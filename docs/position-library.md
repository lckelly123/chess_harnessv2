# PostgreSQL position library

The `positions_db` Docker service stores the fixed training and test library. It
uses PostgreSQL 17 and the persistent `positions_data` named volume. The existing
SQLite match history remains separate. The positional-testing screen reads this
database and runs a selected exercise using its stored PGN history. Model attempts
and per-pass traces are persisted in the same PostgreSQL database. New completed
turns receive automatic Stockfish grades and better-move training targets. The
training/update loop itself remains future work.

The library browser combines set, phase, position type, and side-to-move filters.
Additional filters cover dataset version, source, puzzle theme, and puzzle-rating
band. Search matches opening names, readable theme names, and IDs. This small
library loads its metadata once and filters locally, with 12 results per page.
An unavailable database shows an explicit retry state; an empty database shows
an import prompt. No legacy PGN fixture is used as a fallback.

## Pilot composition

Dataset `v1` contains 400 positions from 400 distinct source games. Both splits
have this composition, with equal White/Black turns inside every cell:

| Phase | Quiet | Tactical | Total per split |
| --- | ---: | ---: | ---: |
| Opening | 32 | 8 | 40 |
| Middlegame | 96 | 24 | 120 |
| Endgame | 32 | 8 | 40 |
| Total | 160 | 40 | 200 |

The seed files in `backend/positional_testing/datasets/seed/v1` are the frozen
artifact. Importing them does not download anything or call a model/engine.
`manifest.json` records the random seed, observed public dataset revisions,
source-page offsets, filtering policy, engine executable hash, and file hashes.
Use a new version when changing positions or their reference evaluations.

## Start and import

From the repository root:

```powershell
docker compose up -d positions_db
docker compose build backend
docker compose run --rm --no-deps backend python -m positional_testing.datasets validate
docker compose run --rm --no-deps backend python -m positional_testing.datasets import
docker compose run --rm --no-deps backend python -m positional_testing.datasets summary
```

Wait for `positions_db` to be healthy before importing. The importer also applies
the additive schema, so it works with an existing database volume. Validation
happens before any data write; all inserts then occur in one transaction. A
second import compares the stored rows and references with the frozen seed and reports
`already_present`. A changed manifest for an existing version is rejected.

Defaults from `.env.example`: host access at `127.0.0.1:5433`, database
`chess_positions`, user `chess`, password `chess_local`. Container access uses
`positions_db:5432`. Change the `POSITIONS_DB_*` settings for your environment;
these are local development defaults. On an existing PostgreSQL volume, changing
the initialization password variable does not change the stored database role.

The CLI can also run from `backend` using its virtual environment and the same
environment variables. Its default host/port are `127.0.0.1:5433`.

`docker compose down` preserves the named volume. `docker compose down -v`
removes it. The frozen seed can restore this library, but run history should
be backed up independently with PostgreSQL's normal backup tools.

## Run history

`model_runs` stores one UUID per positional attempt, its position foreign key,
resolved model, harness, non-secret execution configuration, status, chosen UCI
move, timestamps, and failure message. New completed turns populate `cp_loss`,
`classification`, `expected_points_loss`, `better_moves`, and `evaluation`.
Existing curation references are never presented as a model-run grade.

`model_run_passes` uses `(run_id, pass_number)` as its primary key. Each row groups
one model invocation's emitted working notes and ordered tool-call array, with
phase, status, error and timestamps. A call retains its ID, arguments, exposed
result/error, execution order and relevant board context. Rejected batches mark
rolled-back results and unexecuted calls; proposed notes from failed passes remain
available for diagnosis. Missing notes are left empty, never inferred. Provider
credentials, raw response envelopes and encrypted reasoning are not persisted.

The recorder creates the run before resolving the model, inserts a pass before
calling it, and updates that same pass row as calls return. Ordinary failures and
cancellations retain partial history. A hard process kill may leave an attempt
marked running; automatic recovery of those records is not implemented yet.
Recording is scoped to positional turns, and leaves match tracing unchanged.

Open **Run history** below the position controls. The position filter follows the
selected exercise; exact Position ID and Run ID filters combine, and **All runs**
clears both. Results are paginated in groups of 30. Selecting a run shows its move
and evaluation state above a bounded, keyboard-scrollable pass timeline. Expand
individual calls to inspect arguments, results and board context. Running records
refresh every two seconds. History survives page reloads; earlier transient runs
are not backfilled. The run repository applies the additive schema on first use
so existing Docker volumes receive these tables without reimporting the library.

## Automatic run evaluation

After a positional harness returns its legal move, the runner saves that move,
ends the model recorder context, and invokes Stockfish. The evaluator sees the
original FEN and PGN prefix, including repetition history, and never supplies
scores or candidate answers to the model. The run stays `running` through grading
and becomes `completed` when its grade is saved atomically. HTTP and CLI runs both
use this path. There is no scan, backfill, or mutation of earlier runs.

Docker bundles the official generic x86-64 Stockfish 18 release, pinned by archive
SHA-256. Host execution requires `STOCKFISH_PATH` or `stockfish` on PATH. Each
evaluation gets a fresh engine with one thread, 128 MB hash and native
`UCI_ShowWDL`. Evaluation is serialized within each runner to limit CPU/memory
contention. The default total search budget is 500,000 nodes multiplied by the
number of legal moves, distributed by Stockfish's full MultiPV search, with a
180-second timeout. These settings are exposed as `POSITION_EVAL_NODES_PER_MOVE`,
`POSITION_EVAL_HASH_MB`, and `POSITION_EVAL_TIMEOUT_SECONDS`.

Every legal root move is evaluated. Only the last complete MultiPV depth is used;
partial depths, bounded scores, missing WDL and incomplete coverage cannot
produce a grade. The saved engine name/hash, policy version, settings and actual
depth identify the benchmark. Finite engine searches remain approximations;
changing the budget or engine creates a different evaluation condition.

Policy `expected-points-v1` uses native Stockfish WDL probabilities:

```text
expected_points = (wins + 0.5 * draws) / 1000
expected_points_loss = best.expected_points - chosen.expected_points
```

All scores use the original side to move, including Black. Ranking is descending
expected points, with CP/mate score and then UCI breaking ties. Classification
uses integer half-point units out of 2000 to avoid floating-point boundary drift:

| Classification | Rule |
| --- | --- |
| best | Zero loss and the same CP/mate score as the top candidate |
| excellent | Otherwise loss below 0.02 |
| good | 0.02 to below 0.05 |
| inaccuracy | 0.05 to below 0.10 |
| mistake | 0.10 to below 0.20 |
| blunder | 0.20 or more |

The cutoffs follow [Chess.com's published expected-points bands](https://support.chess.com/en/articles/8572705-how-are-moves-classified-what-is-a-blunder-or-brilliant-etc).
The calibration is [Stockfish self-play WDL](https://github.com/official-stockfish/WDL_model),
not Chess.com's rating-dependent model. A WDL rounding tie alone does not earn
`best`. Mate distances remain separate; `cp_loss` is NULL if either comparison
score is mate. Maintaining a forced win with a slower mate can have zero loss.

`better_moves` stores **only** candidates whose expected points are strictly
higher than the chosen move, in ascending loss order. It is not capped to a top-N
shortlist. Each entry retains UCI/SAN, rank, expected points, loss relative to the
best move, improvement over the chosen move, CP/mate score, native WDL, depth,
and principal variation. Equal-expected-score moves are excluded even when CP
prefers one. An evaluated move with no better target stores `[]`; an unevaluated
run stores NULL. `evaluation` retains `best` and `chosen` details plus provenance.

Engine failure or timeout leaves the successful model trace intact, marks
`evaluation.status` as `failed`, and records the evaluation error without
inventing labels or training targets. Failed model turns are not evaluated.
A process kill can still leave a run `running`; automatic recovery/retry is not
implemented. Use completed evaluations, and filter `positions.split = 'train'`,
when consuming training targets:

```sql
SELECT r.id, r.position_id, r.final_move_uci, r.classification,
       r.expected_points_loss, r.better_moves
FROM model_runs r JOIN positions p ON p.id = r.position_id
WHERE p.split = 'train' AND r.status = 'completed'
  AND r.evaluation->>'status' = 'completed';
```

## Stored data

`positions` has one row per exercise:

| Column | Meaning |
| --- | --- |
| `id` | Stable UUID derived from dataset version, source game, and ply |
| `dataset_version` | Frozen collection membership, initially `v1` |
| `split` | `train` or `test` |
| `phase` | `opening`, `middlegame`, or `endgame` |
| `position_type` | `quiet` or `tactical` |
| `fen` | Full six-field FEN, **after** the last opponent move |
| `pgn_prefix` | Legal game history ending exactly at that FEN |
| `last_move_uci`, `last_move_san` | Last opponent move in machine/display notation |
| `source`, `source_game_id`, `source_ply`, `source_url` | Origin and exact location |
| `position_key` | Hash of board, turn, castling, and legal en-passant rights |
| `metadata` | Source ratings, puzzle themes, license, and curation method |

The PGN has result `*`, no player names, no comments/evaluations, no variations,
and no future moves. Replaying it recreates castling, en passant, repetition
history, and the halfmove clock. **Do not apply `last_move_uci` again** after
loading `fen`. Prefer replaying the prefix when constructing the harness position
so repetition history survives.

`position_datasets` records the immutable manifest and content hash.
`position_evaluations` stores Stockfish reference scores and candidate lines
separately, keyed by position and analysis ID. Scores use the **side-to-move at
the root** perspective; mate distances are stored separately from centipawns.
The payload preserves engine options, search budget, depth, candidate moves, and
screening evidence. Further analyses can use another `analysis_id`.

When exposing exercises to the agent, select only its allowed board/history
inputs. Keep reference evaluations, puzzle ratings/themes, and source links out
of its prompt; those are evaluator/inspection metadata. Keep the test split out
of training updates. These engine references are initial screening measurements,
not human Elo estimates or an implemented reward function.

Example operator queries:

```sql
SELECT split, phase, position_type, count(*)
FROM positions WHERE dataset_version = 'v1'
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

SELECT id, fen, pgn_prefix, last_move_uci, last_move_san
FROM positions
WHERE dataset_version = 'v1' AND split = 'train'
  AND phase = 'middlegame' AND position_type = 'quiet'
ORDER BY id;
```

## Full-set queues

`position_run_queues` stores each batch's dataset version, training/test split,
versioned harness identity, model selection, status, and timestamps.
`position_run_queue_items` freezes its position IDs in deterministic UUID order,
with an ordinal, status, optional `run_id`, failure stage/message, and timestamps.
The linked `model_runs` and `model_run_passes` remain the trace/evaluation store;
run configuration also includes `queue_id` and `queue_ordinal`.

A server worker executes one position, including grading, before claiming the
next. A partial unique index permits only one active queue, and a PostgreSQL
session advisory lock permits only one worker across API processes. Model,
position-validation, grading, and timeout failures are saved on the item and do
not prevent later positions from running. Grading failures preserve completed
model traces; move classifications such as `blunder` are successful executions.
`completed` on a queue means all its positions were attempted, so inspect its
failed count as well. Failures are not retried automatically.

The browser only starts/stops and polls the queue. Closing it does not stop work.
`Stop after current` changes the queue to `stopping`; the active position finishes,
remaining items become `skipped`, and the queue becomes `stopped`. After a backend
restart, a finished grade is retained if it was saved just before interruption.
Otherwise the interrupted item/unfinished trace is marked failed, and remaining
positions continue. Existing unqueued traces are never modified by recovery.
Database outages pause consumption until persistence returns.

`POSITION_QUEUE_ITEM_TIMEOUT_SECONDS` defaults to 1800 seconds for the entire
model turn plus grading. A timed-out position is flagged and the next begins.
The existing 180-second Stockfish timeout still applies within that limit.
The Docker backend must remain running for progress; its restart resumes pending
work automatically. Changing the UI's model or harness cannot change a queue's
captured selection. Each attempt records its actual resolved model/configuration.

The integration tests run a complete 200-position queue using scripted responses,
inject model and engine failures, and check stop/timeout/recovery in temporary
schemas. They make no real model calls and leave the public dataset/history intact:

```powershell
$env:POSITIONS_INTEGRATION_TEST = '1'
python -m pytest tests/positional_testing/test_queue.py -q
```

## Sources and curation

Both sources are public **CC0** Lichess data:

- [Lichess standard games](https://huggingface.co/datasets/Lichess/standard-chess-games)
  supplies real game positions for the quiet portion. Games require both player
  ratings of at least 1600 and estimated time control of at least 600 seconds
  (`initial + 40 × increment`). Player rating is provenance, not position Elo.
- [Lichess puzzles](https://huggingface.co/datasets/Lichess/chess-puzzles)
  supplies rated tactics. Filters require rating 1000–2400, rating deviation at
  most 100, popularity at least 70, and at least 100 plays. Original game history
  is retrieved from Lichess and replayed to the puzzle.
- [Lichess database documentation](https://database.lichess.org/#puzzles)
  explains that the puzzle FEN precedes its setup move. That first move is applied
  once, then the resulting position is matched to the original game history.

Sampling uses seeded random pages of 100 records, shuffles records within pages,
and selects at most one exercise per game. Quiet candidates are shuffled and
sampled across phases. This is a stratified pilot, not a statistically uniform
sample of all Lichess positions. Rows are shuffled within phase/type/side buckets
before splitting; the same source game or normalized board cannot occur twice.

Phase labels use a documented material heuristic: knight/bishop = 1, rook = 2,
queen = 4, summed across both sides. Endgames have total at most 8; openings have
total at least 18 and fullmove at most 12; middlegames have total at least 10 and
fullmove at least 13. Ambiguous boundaries are excluded. Quiet openings also
start at fullmove 6. Tactical phases must agree with the source puzzle theme.

Quiet screening uses Stockfish 18, one thread, 128 MB hash, cleared between
searches, three principal variations, 80,000 screening nodes and 500,000 reference
nodes. The final complete MultiPV depth is used, avoiding partial/bounded output
from an interrupted next-depth search. At both budgets:

- The position is not in check or terminal/draw-claimable; it has at least eight
  pieces, six legal moves, and at most 300 cp initial material imbalance.
- Best evaluation is within ±180 cp, with no mate score among the top three.
- The best move is not a capture, check, or promotion, and at least two of the
  top three candidates are nonforcing.
- Best and second-best scores differ by at most 100 cp.
- The best PV has at least eight plies, with at most 100 cp net material change
  over its first ten plies (or the available line when shorter).
- Best evaluation changes by at most 40 cp between search budgets.

These are **engine-screened quiet candidates**, not a proof of tactical absence.
The initial selection favors balanced positions and excludes elementary sparse
endings; that is intentional for this game-sense pilot. Quiet positions have no
invented difficulty rating. Tactical positions retain their Lichess puzzle rating,
must have a legal source solution, and must agree with the engine's first move.
Mate-themed puzzles are capped at half of each tactical phase across the library.

## Re-curation and checks

To build a separate version from public sources, run from `backend` with a local
Stockfish executable:

```powershell
python -m positional_testing.datasets.curate --engine C:\path\to\stockfish.exe --version v2 --seed 20260923
```

Downloads, engine caches, and resumable progress go under ignored
`backend/data/position_curation/<version>`. Re-run the same command to resume.
This command explicitly uses the network and engine. Public sources can change;
the committed seed files are the reproducible evaluation artifact, while a fresh
curation is a new collection. No model calls or LangSmith uploads are required.

From `backend`, with development requirements installed:

```powershell
python -m pytest tests/positional_testing/test_datasets.py -q
$env:POSITIONS_INTEGRATION_TEST = '1'
python -m pytest tests/positional_testing/test_datasets.py -q
```

The second command also checks real PostgreSQL imports, idempotence, frozen-version
protection, and transaction rollback in temporary test schemas. It does not modify
the populated public schema.
