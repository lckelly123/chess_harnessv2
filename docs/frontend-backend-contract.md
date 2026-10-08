# Frontend ↔ backend contract

The browser is a spectator and controller for match lifecycle and one-turn positional tests. It never decides a chess move, validates legality, advances a clock, computes a result, or invents a trace. Those are backend responsibilities.

## What crosses the boundary

| Direction | Information | Why the frontend needs it |
| --- | --- | --- |
| Backend → frontend | Harness ids, names, and versions | Populate the two player selectors and preserve reproducibility. |
| Frontend → backend | White and black harness ids | Request a new match using two known implementations. |
| Backend → frontend | Folder ids, names, and match counts | Render durable organizational groups without deriving them in the browser. |
| Frontend → backend | Folder name or match-folder assignment | Create a named folder, file a new match, or move an existing record. |
| Backend → frontend | Match id, folder, status, players, timestamps, result, current FEN, move count | Render the authoritative state and identify the record. |
| Backend → frontend | Ordered positions with ply, FEN, SAN, and changed squares | Display and replay a position without running chess logic in React. |
| Backend → frontend | Ordered trace events with ply, player, phase, status, summary, and detail | Explain what the harness was doing at each point. |
| Frontend → backend | Match id to stop | Request cancellation of the active run. The backend decides the terminal state. |
| Frontend → backend | Search text and optional folder filter | Filter previous match records. |
| Backend → frontend | Saved PGN summaries and final board snapshots | Let the user inspect curated positions without parsing chess data in React. |
| Frontend → backend | Saved position id and harness id | Request exactly one harness turn without creating a match. |
| Backend → frontend | Proposed move, resolved model, justification, and optional phase reports | Present the authoritative one-turn result while leaving the saved board unchanged. |

The TypeScript source of truth for the client is [`frontend/src/api/contracts.ts`](../frontend/src/api/contracts.ts). Match API models live in [`backend/app/models.py`](../backend/app/models.py), while positional-test models live in [`backend/positional_testing/models.py`](../backend/positional_testing/models.py).

## HTTP surface

| Method | Route | Current behavior |
| --- | --- | --- |
| `GET` | `/api/health` | Reports SQLite storage and model-selection mode. |
| `GET` | `/api/harnesses` | Returns the two registered LangGraph harness versions. |
| `GET` | `/api/folders` | Returns named folders and durable match counts. |
| `POST` | `/api/folders` | Creates a unique, case-insensitive named folder. |
| `GET` | `/api/matches?query=...&folder_id=...&unfiled_only=...` | Searches durable SQLite records. `folder_id` scopes a named folder; `unfiled_only=true` selects records without a folder, and the two filters are mutually exclusive. |
| `GET` | `/api/matches/{matchId}` | Returns positions and trace events for one record. |
| `POST` | `/api/matches` | Creates a match in an optional folder and starts its background runner. |
| `PATCH` | `/api/matches/{matchId}/folder` | Moves a match into a folder or back to Unfiled. |
| `POST` | `/api/matches/{matchId}/stop` | Cancels the runner and prevents a late move commit. |
| `DELETE` | `/api/matches/{matchId}` | Permanently deletes the match, replay positions, and public events. Preserves its folder; folder counts are derived from remaining matches. Returns empty 204, missing record 404, or active (`queued`/`running`) match 409 with stop instructions. |
| `GET` | `/api/positional-testing/positions` | Reads the PostgreSQL position library. Returns UUID, name, datasetVersion, split, phase, positionType, source/game/link, opening, themes, puzzleRating, sideToMove, moveCount, and board snapshot. History and engine references are excluded. The small-library UI filters these summaries locally. |
| `POST` | `/api/positional-testing/queues` | Accepts `datasetVersion`, `split` (`train`/`test`), `harnessId`, optional `modelSelection`, and optional `name` (up to 120 characters after whitespace normalization; blank/null/omitted means unnamed). Names need not be unique. Snapshots all matching IDs and configuration, returns 202 with queue detail including nullable `name`. Empty set/unknown harness/invalid name returns 422; another active queue returns 409. Execution runs independently of the request. |
| `GET` | `/api/positional-testing/queues` | Latest 20 queue summaries with nullable `name` and durable completed/failed/pending/running/skipped counts. |
| `GET` | `/api/positional-testing/queues/{queueId}` | Derived queue summary and all ordered run rows (each has a run ID from enqueue), including position/run IDs, tags, chosen move/classification, status, failure stage/error, and timestamps. Unknown UUID returns 404. |
| `POST` | `/api/positional-testing/queues/{queueId}/stop` | Idempotent stop-after-current request. The current attempt finishes; unstarted positions are marked skipped. Unknown UUID returns 404. |
| `DELETE` | `/api/positional-testing/queues/{queueId}` | Atomically deletes every run and model pass with this exact queue UUID, including rows outside UI filters or pagination. Any queued/running member rejects the whole operation with 409; stop and wait for the current run first. Preserves source positions and other queues, including identically named queues. Returns empty 204, unknown queue 404, malformed UUID 422, or unavailable database 503. Uses the queue worker's state lock. |
| `POST` | `/api/positional-testing/runs` | Loads the position UUID from PostgreSQL, verifies its PGN reproduces the FEN/last move, and invokes the selected harness once. Only board/history enter the turn request. Returns the move and reports without persisting a match or changing the library. Unknown IDs return 404, database failures 503, and inconsistent history 500. |
| `GET` | `/api/positional-testing/runs` | Persistent attempts, newest first by creation time with a stable ID tie-breaker. Exact `position_id`, `run_id`, and `queue_tag` UUID filters combine with `split`, `dataset_version`, `harness`, `model`, `status`, `analysis` (`completed`/`failed`/`missing`), `classification`, `run_source` (`single`/`queue`), and literal case-insensitive `query` search across IDs, harness, model, and phase. `sort` is `newest` or `oldest`; `limit` is 1–100 (default 30), `offset` defaults to 0. Filtering happens before pagination; `total` counts all matches. Summaries omit passes and include `positionFen`, `datasetVersion`, `split`, `phase`, `positionType`, and `analysisStatus` alongside existing grades, timestamps, status, and nullable `queueTag`. Queue split/dataset use the captured configuration. Standalone attempts have `queueTag: null`. |
| `GET` | `/api/positional-testing/run-filters` | Datasets, resolved models, harness IDs/names, and dated queue choices from the entire saved run history, including older queues and retired harnesses. Queue choices contain `id`, nullable `name`, `datasetVersion`, `split`, `harnessName`, and `createdAt`. Does not use the latest-20 queue limit. |
| `GET` | `/api/positional-testing/runs/{runId}` | One attempt with nullable `queueTag` and ordered `passes`. Each pass has `passNumber`, `phase`, emitted `workingNotes`, grouped `toolCalls`, status/error, timestamps, and `hasModelExchange`. Raw input/output are omitted from polling. Unknown UUID returns 404; malformed UUID returns 422; unavailable database returns 503. |
| `DELETE` | `/api/positional-testing/runs/{runId}` | Deletes one run and its model passes, preserving the source position and sibling runs. Queue counts and filter options reflect surviving runs; deleting the final member removes the derived queue. Returns empty 204, missing run 404, queued/running run 409, malformed UUID 422, or unavailable database 503. |
| `GET` | `/api/positional-testing/runs/{runId}/passes/{passNumber}/exchange` | Lazy read of one saved exchange: `input` is the complete captured provider request body formatted as JSON; `output` is an ordered array of unmodified returned text/reasoning/refusal and native function-argument strings. No generated output is an empty array. Missing run/pass returns 404, uncaptured historical pass 409, invalid UUID/nonpositive pass 422, unavailable database 503. |

FastAPI also exposes an interactive schema at [http://localhost:8000/docs](http://localhost:8000/docs) while the Docker stack is running.

Run summaries and details expose nullable `queueName`, projected from the saved
`config.queue.name`. Literal `query` search also matches this name. Queue names
are display/search metadata; all queue selection, filtering, and stop operations
continue to use the stable queue UUID. Older unnamed queues require no migration.

## LangGraph integration

Both start endpoints accept an optional `modelSelection` object:

```json
{"modelId": "gpt-terra", "reasoningEffort": "medium"}
```

`modelId` is restricted to `qwen` or `gpt-terra`; the only selectable reasoning
effort is `medium`. Omission keeps the existing LM Studio default. The backend
maps `gpt-terra` to `gpt-5.6-terra`, resolves one client/configuration per run, and
does not accept provider URLs or credentials from the browser. A match uses that
selection for both players. Invalid selections return 422; missing GPT
credentials return 503; positional attempts retain a failed run record. Positional provider failures return
502; provider failures during a match mark that match failed. There is no fallback
to another model. Forced-format retries retain their separate no-reasoning policy.

The match runner calls the selected graph once per turn and uses `game_id` as the
LangSmith `thread_id`. SQLite public events describe turn starts, committed moves,
and terminal states. React does not receive raw graph state, model secrets,
provider responses, or the LangSmith API key.

Polling remains the deliberate first transport. SSE or WebSockets can be added
later if node-level live progress is worth the extra reconnect and ordering logic.
Positional POST requests remain synchronous and retain their completed public
response shape, now with a durable UUID `runId`. A turn-scoped observer persists
one run row and one aggregate row per model pass. The history UI polls running
records every two seconds, even while the POST is pending. Exposed tool payloads,
working notes, retry errors and rollback markers are inspection data and never
added to the model's input by the recorder. LangSmith remains available separately.
After the model turn finishes, its move is saved and Stockfish evaluates all legal
alternatives. The run remains `running` while this evaluation completes, so the
existing poll continues. The POST returns after the grade is committed. History
responses expose nullable `cpLoss`, `classification`, `expectedPointsLoss`,
`betterMoves`, and `evaluation`. The classification is one of `best`, `excellent`,
`good`, `inaccuracy`, `mistake`, or `blunder`.

`betterMoves` is a JSON array ordered by ascending expected-points loss from the
best move. It contains every legal move with strictly greater expected points
than the chosen move, excluding equal/lower scores; an empty array means no
strictly better target. Each entry uses snake_case keys: `rank`, `move_uci`,
`move_san`, `expected_points`, `expected_points_loss`, `improvement_over_chosen`,
`score_cp`, `mate`, `wdl`, `depth`, and `pv_uci`. `wdl` contains integer `wins`,
`draws`, and `losses` totaling 1000, from the original mover's perspective.

`evaluation` records engine identity/hash, the versioned policy, search budget,
complete depth, legal/evaluated counts, timestamps, and `best`/`chosen` move
details. A grading failure preserves the chosen move and completed passes, sets
the run's `status = "failed"` and `failureStage = "evaluation"`, and records
`evaluation.status = "failed"` and an `error`; its numerical scores and targets
stay null. Older runs stay null and are never backfilled. Mate scores keep CP
loss null. The existing UI displays the classification and CP loss, with the
evaluation metadata available under Run details.
