# Chess Harness v2

A local observability console for agent-versus-agent chess matches. The current slices contain a React match desk, a deliberately small FastAPI mock service, a tested deterministic chess core, and standalone LangGraph Agent Player 1 and submit-only baseline harnesses for LM Studio with optional LangSmith tracing. The frontend still uses mock matches; the agents are not yet connected to a match runner.

## Run locally with Docker

Prerequisite: Docker Desktop with Compose.

```powershell
docker compose up --build
```

Then open:

- frontend: [http://localhost:5173](http://localhost:5173)
- mock API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

Stop the stack with `docker compose down`.

## Repository shape

```text
backend/
  app/                 FastAPI routes, public models, and in-memory mock data
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

For a live run, configure LM Studio and the optional LangSmith credentials using [.env.example](.env.example). See [Agent Player 1 setup and migration notes](docs/agent-player-1.md). Starting the normal web stack does not automatically run an agent.

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
See [baseline setup and migration notes](docs/baseline.md). LangSmith Studio and
full-game orchestration are not configured yet.

## Deterministic chess core

`backend/chess_core` wraps `python-chess` behind immutable, serializable records. It validates and applies SAN or UCI moves, reports terminal position status, maintains isolated turn-local scratchboards, inspects square control, calculates static exchanges, and scans forcing moves. Canonical match state is not stored in this package; the later match runner will own and persist it.

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
docker run --rm --network none chess-harness-v2-agent-test ruff check harness tests/harness
docker run --rm --network none chess-harness-v2-agent-test ruff format --check harness tests/harness
```
