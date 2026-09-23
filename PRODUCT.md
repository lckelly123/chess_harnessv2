# Chess Harness v2

## Product

Chess Harness v2 is a local, developer-facing observability console for autonomous chess agents. It exists to make agent-v-agent matches reproducible, inspectable, and easy to compare while the underlying harness is rebuilt around LangGraph.

## Audience

The primary user is the developer or researcher building the harness. They need to see what the backend decided, which harness version acted, how the position changed, and which trace events explain the move. They can also invoke one agent turn against a curated position or evaluate a full training/test set without starting a match.

## First surface

The first release is a React web interface served locally through Docker. It lets the user:

- select the white and black harness versions;
- start and stop an agent-v-agent match;
- watch the backend-authored position, status, clocks, and trace stream;
- search previous matches;
- create named game folders and file new or existing matches into them;
- open and replay a completed match move by move;
- filter the PostgreSQL position library by set, phase, type, side, dataset, source, theme, and puzzle rating; choose a harness and request one proposed move;
- run every position in a dataset's training or test set sequentially, monitor progress, and inspect saved results and failed attempts.

Match history uses a local SQLite-backed runner; the curated training/test
position library uses PostgreSQL in Docker. The UI talks only
to a typed backend API and polls authoritative snapshots while the selected agents
run in the background.

## Product boundaries

- The backend is authoritative for match state, legal moves, results, and traces.
- The frontend never chooses chess moves and exposes no human move controls.
- Public UI events summarize match progress; detailed graph execution remains in LangSmith.
- Positional-test attempts and per-pass working notes/tool results persist in PostgreSQL. They do not create a match record or mutate the saved PGN. Successful Stockfish evaluations record an expected-points-loss classification and all strictly better legal moves for future training. Grading failures retain the model trace and error; existing runs are not backfilled.
- Full-set queues capture their dataset, split, harness, model selection, and position membership when created, regardless of library filters. One queue runs at a time, completing each model turn and evaluation before the next position. Execution, validation, evaluation, and timeout failures are flagged in PostgreSQL and the queue continues. Closing the browser does not stop it; a backend restart resumes pending positions without replaying interrupted attempts.
- The first release stays deliberately small: no authentication, tournaments, agent configuration editor, or trace mutation.
- Harness selections are versioned identifiers, not editable prompts.
- Stopping a match ends the active local match. Stopping a queue lets the current position finish and marks the remaining positions skipped; saved results remain available.

## Information contract

The frontend needs seven backend-facing resources:

1. **Harness versions** — stable id, display name, version, and short description.
2. **Game folders** — stable id, user-defined name, and match count for durable organization.
3. **Match summary** — id, folder, players, status, result, timestamps, current FEN, move count, and last move.
4. **Match detail** — the summary plus chronological positions/moves and structured trace events.
5. **Match commands and updates** — start, stop, folder assignment, and polled snapshots with a possible future server-sent event stream.
6. **Positional tests** — PostgreSQL exercise summaries with visible/filterable classifiers, a one-turn command, and saved attempts with the selected harness, resolved model, proposed legal move, emitted notes/tool results, and evaluation. Engine references and exercise classifications stay out of model inputs.
7. **Full-set queues** — start/stop commands and durable snapshots containing captured configuration, progress counts, ordered position statuses, failure details, and links to saved attempts.

Every trace event has a stable id, timestamp, ply, player, phase, status, short summary, and optional structured detail. The browser may format and filter these fields, but it does not infer hidden backend state.

## Product principles

- **Explain the move, not just the board.** Match position and causal trace stay visible together.
- **Backend truth stays intact.** Transport and presentation layers may change; match semantics do not.
- **Version everything worth comparing.** Harness identity belongs on every match and historical record.
- **Simple seams over speculative frameworks.** Introduce an interface where replacement is expected, not abstractions everywhere.
- **Local-first professional workflow.** One documented Docker command should produce a working development surface.

## Experience direction

This is an operations surface for sustained desktop use, with responsive support for narrow screens. It should feel calm, precise, and legible rather than playful or game-like. The visual hierarchy should lead from the live board to the active agent phase, then to the chronological trace. Historical matches should remain easy to scan and replay.

## Accessibility and quality

- Keyboard-visible focus for every interactive control.
- Sufficient text and control contrast.
- Status is communicated by words and structure, not color alone.
- Controls have explicit labels and disabled states.
- Layout remains usable at common desktop and mobile widths.
