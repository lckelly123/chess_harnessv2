---
version: 1
slug: "frontend-index-html"
primary_target: "frontend/index.html"
related_targets: ["frontend/src/App.tsx","frontend/src/styles.css","frontend/src/components/FolderRail.tsx","frontend/src/components/HistoryList.tsx","frontend/src/components/MatchDocket.tsx","frontend/src/components/MatchStatus.tsx"]
---

# Match desk surface

- Scope: the single-page local match desk in `frontend/`; visitor mode is Operate.
- Audience and job: a harness developer selects two versioned agents, files the run into a named experiment folder, watches backend-authored state and causal trace, then searches and replays durable records.
- Primary actions: select harnesses and a game folder, start or stop a match, create a named folder, filter or refile historical matches, open a record, and move its replay cursor.
- Content: typed harness, folder, match, position, player, and trace data from the SQLite-backed FastAPI service.
- Constraints: spectator-only; no legal-move or agent logic in React; folders are organizational metadata rather than filesystem directories; no auth, tournaments, configuration editor, or hidden-state inference.
- Interaction behavior: refiling remains local to the affected history row, which owns its disabled, progress, and error states without blocking the rest of the ledger.
- Responsive behavior: the filing index stacks above the records on narrow screens, and the trace receives a bounded scroll region so folder controls and match records remain reachable.
- Direction: a tournament arbiter's match ledger. Vellum, graphite, tournament green, rust stop marks, square cells, and tabular annotations. The folder rail extends the ledger as a compact filing index rather than a separate dashboard.
- Memorable moment: one replay registration mark keeps board position, move notation, and causal trace on the same ply while the filing index preserves the experiment context.
- Unresolved: polling remains adequate for current match snapshots; SSE or WebSockets can be revisited if node-level progress is exposed.
