# Frontend ↔ backend contract

The browser is a spectator and controller for match lifecycle. It never decides a chess move, validates legality, advances a clock, computes a result, or invents a trace. Those are backend responsibilities.

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

The TypeScript source of truth for the client is [`frontend/src/api/contracts.ts`](../frontend/src/api/contracts.ts). The equivalent API models live in [`backend/app/models.py`](../backend/app/models.py).

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

FastAPI also exposes an interactive schema at [http://localhost:8000/docs](http://localhost:8000/docs) while the Docker stack is running.

## LangGraph integration

The match runner calls the selected graph once per turn and uses `game_id` as the
LangSmith `thread_id`. SQLite public events describe turn starts, committed moves,
and terminal states. React does not receive raw graph state, model secrets,
provider responses, or the LangSmith API key.

Polling remains the deliberate first transport. SSE or WebSockets can be added
later if node-level live progress is worth the extra reconnect and ordering logic.
