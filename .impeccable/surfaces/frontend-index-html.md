---
version: 1
slug: "frontend-index-html"
primary_target: "frontend/index.html"
related_targets: ["frontend/src/App.tsx","frontend/src/styles.css"]
---

# Match desk surface

- Scope: the single-page local match desk in `frontend/`; visitor mode is Operate.
- Audience and job: a harness developer selects two versioned agents, watches backend-authored state and causal trace, stops a run, then searches and replays prior records.
- Primary actions: start a mock match, stop the active match, open a historical record, and move its replay cursor.
- Content: typed illustrative match, move, position, player, and trace data from the mock FastAPI service. Synthetic data is labeled in the interface.
- Constraints: spectator-only; no legal-move or agent logic in React; no auth, tournaments, configuration editor, or hidden-state inference.
- Direction: a tournament arbiter's match ledger. Vellum, graphite, tournament green, rust stop marks, square cells, and tabular annotations.
- Memorable moment: one replay registration mark keeps board position, move notation, and the causal trace on the same ply.
- Unresolved: the real backend transport may become polling, SSE, or WebSocket after the LangGraph event contract is implemented.
