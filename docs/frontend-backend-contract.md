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
| `GET` | `/api/positional-testing/positions` | Returns selectable final positions parsed from saved PGNs. |
| `POST` | `/api/positional-testing/runs` | Invokes the selected harness once and returns its move and reports. It does not persist a match or modify the PGN. |

FastAPI also exposes an interactive schema at [http://localhost:8000/docs](http://localhost:8000/docs) while the Docker stack is running.

## LangGraph integration

Both start endpoints accept an optional `modelSelection` object:

```json
{"modelId": "gpt-luna", "reasoningEffort": "medium"}
```

`modelId` is restricted to `qwen` or `gpt-luna`; the only selectable reasoning
effort is `medium`. Omission keeps the existing LM Studio default. The backend
maps `gpt-luna` to `gpt-5.6-luna`, resolves one client/configuration per run, and
does not accept provider URLs or credentials from the browser. A match uses that
selection for both players. Invalid selections return 422; missing GPT
credentials return 503 without starting a run. Positional provider failures return
502; provider failures during a match mark that match failed. There is no fallback
to another model. Forced-format retries retain their separate no-reasoning policy.

The match runner calls the selected graph once per turn and uses `game_id` as the
LangSmith `thread_id`. SQLite public events describe turn starts, committed moves,
and terminal states. React does not receive raw graph state, model secrets,
provider responses, or the LangSmith API key.

Polling remains the deliberate first transport. SSE or WebSockets can be added
later if node-level live progress is worth the extra reconnect and ordering logic.
Positional runs are synchronous one-turn requests; detailed execution remains in
LangSmith and the browser receives only the completed public result.
