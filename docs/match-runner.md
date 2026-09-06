# Real local match runner

The match runner is deterministic application orchestration around two independent
move-producing LangGraphs. It owns the canonical `python-chess` board, supplies a
FEN and matching PGN to the correct player, validates the returned SAN again,
commits the move only while the match remains active, and records the resulting
position in SQLite.

## Runtime boundaries

- `app/matches/catalog.py` exposes stable player IDs and builds the selected graph
  wrappers with one resolved LM Studio model for the match.
- `runner.py` alternates turns, preserves board history for draw rules, plays to
  a rule-derived result, and never invents a fallback move.
- `manager.py` owns background tasks, the one-match admission limit, cancellation,
  and conversion of runner exceptions into durable failed records.
- `repository.py` stores named game folders, matches, positions, explanations,
  reports, and public progress events. Its conditional move commit is the final
  stop-race guard.
- `app/routes.py` is the thin REST boundary consumed by React.

Detailed prompts, graph nodes, retries, and tool calls remain in LangSmith. The UI
receives only public match state and explanation events. All turns use the match ID
as their LangSmith thread ID, so the two players' independent root traces can be
viewed as one game history.

## Local configuration

The Docker Compose defaults allow one active match. There is no match-length or
wall-clock turn limit: play continues until checkmate or another rule-derived
result, unless an agent graph fails or the user stops the match. An omitted pawn
promotion piece defaults to a queen; explicit underpromotions remain available.
SQLite data lives in the `backend_data` named volume and therefore survives
container recreation. `docker compose down -v` explicitly removes that volume
and its match history.

When `LMSTUDIO_MODEL` is blank, match creation queries LM Studio's native model
inventory and requires exactly one loaded language/vision-language model. An
explicit value takes precedence. The selected identifier is fixed in both graph
configurations for that match, including forced retries.

```powershell
docker compose up -d --build
```

Open [http://localhost:5173](http://localhost:5173), choose the two harnesses, and
start a match. The frontend polls durable snapshots every three seconds. With
LangSmith tracing enabled, use the configured project to inspect each turn's full
graph trace.

## Verification strategy

Automated tests use scripted legal-move players and temporary SQLite files. They do
not contact LM Studio or LangSmith. A live UI smoke run is the integration test for
the loaded model's protocol compliance, latency, and trace upload configuration.
