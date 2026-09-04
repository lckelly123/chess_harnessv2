# Chess Harness v2

A local observability console for agent-versus-agent chess matches. This first slice contains a React match desk and a deliberately small FastAPI mock service; no chess engine, agent, or LangGraph run is active yet.

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
  tests/               API contract tests
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

The development images include the language runtime, installed dependencies, and application source. The frontend production stage contains only Nginx, its config, and the compiled `dist/` output; it does not ship Node.js or source dependencies. The backend production stage contains Python, installed runtime packages, and `backend/app`. Git history, local virtual environments, test caches, frontend `node_modules`, and secrets are excluded.

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
