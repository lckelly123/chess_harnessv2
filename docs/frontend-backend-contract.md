# Frontend ↔ backend contract

The browser is a spectator and controller for match lifecycle. It never decides a chess move, validates legality, advances a clock, computes a result, or invents a trace. Those are backend responsibilities.

## What crosses the boundary

| Direction | Information | Why the frontend needs it |
| --- | --- | --- |
| Backend → frontend | Harness ids, names, and versions | Populate the two player selectors and preserve reproducibility. |
| Frontend → backend | White and black harness ids | Request a new match using two known implementations. |
| Backend → frontend | Match id, status, players, timestamps, result, current FEN, move count | Render the authoritative state and identify the record. |
| Backend → frontend | Ordered positions with ply, FEN, SAN, and changed squares | Display and replay a position without running chess logic in React. |
| Backend → frontend | Ordered trace events with ply, player, phase, status, summary, and detail | Explain what the harness was doing at each point. |
| Frontend → backend | Match id to stop | Request cancellation of the active run. The backend decides the terminal state. |
| Frontend → backend | Search text | Filter previous match records. |

The TypeScript source of truth for the client is [`frontend/src/api/contracts.ts`](../frontend/src/api/contracts.ts). The equivalent API models live in [`backend/app/models.py`](../backend/app/models.py).

## Mock HTTP surface

| Method | Route | Current behavior |
| --- | --- | --- |
| `GET` | `/api/health` | Identifies the service as a mock. |
| `GET` | `/api/harnesses` | Returns three illustrative harness versions. |
| `GET` | `/api/matches?query=...` | Searches an in-memory list. |
| `GET` | `/api/matches/{matchId}` | Returns positions and trace events for one record. |
| `POST` | `/api/matches` | Creates an in-memory mock match from two harness ids. |
| `POST` | `/api/matches/{matchId}/stop` | Marks an in-memory running match as stopped. |

FastAPI also exposes an interactive schema at [http://localhost:8000/docs](http://localhost:8000/docs) while the Docker stack is running.

## Later LangGraph integration

The route shapes can remain stable while their implementations change. A match service can invoke the graph, persist graph/checkpoint identifiers with the match, and translate graph events into the public `TraceEvent` shape. Live updates can then add an SSE or WebSocket route. React should subscribe to public match events; it should not receive raw internal graph state, model secrets, or provider-specific response objects.

Potential future event types are `match.snapshot`, `move.committed`, `trace.appended`, and `match.ended`. Every event should include the match id, a monotonically increasing sequence number, and a schema version so reconnects and replays are deterministic.

