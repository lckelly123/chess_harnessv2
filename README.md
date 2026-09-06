# Chess Harness v2

A local observability console for agent-versus-agent chess matches. A React match
desk controls a deterministic FastAPI match runner, SQLite stores replayable
positions and public events, and two independent LangGraph harnesses call a model
served by LM Studio. Optional LangSmith tracing records each agent turn.

Named game folders are SQLite-backed collections: choose one before starting a
match, filter the record ledger by folder, or refile an existing match afterward.

## Run locally with Docker

Prerequisites: Docker Desktop with Compose and an LM Studio server with one loaded
language model. Copy `.env.example` to `.env`; a blank `LMSTUDIO_MODEL` selects the
only loaded model, while multiple loaded models require an explicit identifier.

```powershell
docker compose up --build
```

Then open:

- frontend: [http://localhost:5173](http://localhost:5173)
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

Stop the stack with `docker compose down`.

## Repository shape

```text
backend/
  app/                 FastAPI routes plus SQLite-backed match orchestration
  chess_core/          Deterministic position, scratchboard, inspection, and SEE logic
  harness/             Independent agent_player_1 and baseline graphs; shared transport/protocol
  tests/               API, chess-core, graph, prompt-parity, and tracing tests
  Dockerfile           Python development and production stages
frontend/
  src/api/             Typed frontend/backend boundary
  src/components/      Board, match controls, trace, replay, and history UI
  Dockerfile           Vite development and Nginx production stages
docs/
  frontend-backend-contract.md
compose.yaml            Local two-service development stack
PRODUCT.md              Product truth and scope
```

The development images include the language runtime, installed dependencies, and application source. The frontend production stage contains only Nginx, its config, and the compiled `dist/` output; it does not ship Node.js or source dependencies. The backend production stage contains Python, installed runtime packages, `backend/app`, `backend/chess_core`, and `backend/harness` (including its prompts). Test tooling stays in the test stage. Git history, local virtual environments, test caches, frontend `node_modules`, and secrets are excluded.

## Agent Player 1

Run a scripted turn without model calls or trace uploads:

```powershell
docker compose run --build --rm --no-deps -e LANGSMITH_TRACING=false backend python -m harness.agent_player_1 --demo
```

Print the actual compiled graph as Mermaid:

```powershell
docker compose run --rm --no-deps -e LANGSMITH_TRACING=false backend python -m harness.agent_player_1 --diagram
```

For a live run, configure LM Studio and optional LangSmith credentials using
[.env.example](.env.example). See [Agent Player 1 setup and migration
notes](docs/agent-player-1.md). The web stack calls an agent only after a match is
started through the UI or API.

## Submit-only baseline

The baseline preserves the old Agent Player 2's position inputs and `submit_move`
tool, with its own two-node LangGraph and v2's LM Studio text-tool retry protocol.
It does not receive SEE summaries, scratch tools, or phased reports.

Run its scripted demo without model calls or trace uploads:

```powershell
docker compose run --build --rm --no-deps -e LANGSMITH_TRACING=false backend python -m harness.baseline --demo
```

Use `--diagram` to print the compiled graph, `--list-models` to list LM Studio's
served model IDs, or omit the flag for one live move decision. Both harnesses use
the same environment settings and can log to the same LangSmith tracing project.
See [baseline setup and migration notes](docs/baseline.md). LangSmith Studio is a
separate optional setup; UI-started match turns are traced without it. To inspect
either production graph node by node in Studio, follow the
[LangSmith Studio guide](docs/langsmith-studio.md).

## Deterministic chess core

`backend/chess_core` wraps `python-chess` behind immutable, serializable records. It validates and applies SAN or UCI moves, reports terminal position status, maintains isolated turn-local scratchboards, inspects square control, calculates static exchanges, and scans forcing moves. The match runner owns the authoritative board and stores every committed position in SQLite.

The package is named `chess_core` instead of `chess` so it cannot shadow the third-party `chess` Python module.

## Checks

```powershell
cd frontend
npm install
npm run lint
npm test
npm run build

cd ../backend
python -m pip install -r requirements-dev.txt
python -m pytest
```

See [the frontend/backend contract](docs/frontend-backend-contract.md) for the exact data that crosses the boundary and how it can evolve into a LangGraph-backed service.

Run all backend tests without networking:

```powershell
docker build --target test -t chess-harness-v2-agent-test ./backend
docker run --rm --network none chess-harness-v2-agent-test
docker run --rm --network none chess-harness-v2-agent-test ruff check app chess_core harness tests
docker run --rm --network none chess-harness-v2-agent-test ruff format --check app chess_core harness tests
```
