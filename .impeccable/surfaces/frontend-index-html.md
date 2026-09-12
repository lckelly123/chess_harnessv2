---
version: 1
slug: "frontend-index-html"
primary_target: "frontend/index.html"
related_targets: ["frontend/src/App.tsx","frontend/src/styles.css","frontend/src/components/Chessboard.tsx","frontend/src/components/FolderRail.tsx","frontend/src/components/HistoryList.tsx","frontend/src/components/MatchDocket.tsx","frontend/src/components/MatchStatus.tsx","frontend/src/components/PositionalTesting.tsx"]
---

# Match desk surface

- Scope: the single-page local harness desk in `frontend/`; visitor mode is Operate. Its header switches between the match desk and positional testing without introducing a separate visual world.
- Audience and job: a harness developer runs and inspects agent matches, or opens a saved PGN position and asks one versioned agent for a single proposed move.
- Primary actions: select harnesses and a game folder, start or stop a match, create a named folder, filter or refile historical matches, open and replay a record, enter positional testing, choose a saved position, choose Baseline or Agent Player 1, and run that harness once.
- Content: typed harness, folder, match, position, player, trace, saved-PGN, and one-turn result data from the FastAPI service. Positional files come from `backend/positional_testing/positions`.
- Constraints: no legal-move or agent logic in React; folders are organizational metadata rather than filesystem directories; a positional run is transient, does not create a match, and never mutates its saved PGN.
- Interaction behavior: refiling remains local to the affected history row. Positional testing uses staged disclosure—section button, saved-position ledger, selected board, harness radio choices, run action, then move and report—with explicit loading, empty, unavailable, missing-harness, running, run-error, retry, and completed states. Position and harness selection are locked during a run, and the mounted run state survives workspace navigation.
- Responsive behavior: the filing index and positional position index stack above their primary content on narrow screens. Paired harness choices and phase reports become ruled vertical rows, the run action stacks beneath its context, and the trace keeps a bounded scroll region.
- Direction: a tournament arbiter's ledger. Vellum, graphite, tournament green, rust stop and move marks, square cells, and tabular annotations carry both workspace sections.
- Memorable moment: a completed one-turn test registers the proposed path on the unchanged board and sets the SAN in oversized rust type above the harness justification and phase reports.
- Unresolved: polling remains adequate for current match snapshots; SSE or WebSockets can be revisited if node-level progress is exposed. Positional runs intentionally wait on one synchronous HTTP request for now.
