# Chess Harness v2

## Product

Chess Harness v2 is a local, developer-facing observability console for autonomous chess agents. It exists to make agent-v-agent matches reproducible, inspectable, and easy to compare while the underlying harness is rebuilt around LangGraph.

## Audience

The primary user is the developer or researcher building the harness. They need to see what the backend decided, which harness version acted, how the position changed, and which trace events explain the move. They can also invoke one agent turn against a curated position or evaluate a full training/test set without starting a match.

## First surface

The first release is a React web interface served locally through Docker. It lets the user:

- select the white and black harness versions;
- choose LM Studio, Unsloth, or OpenAI for model requests, and discover and select exact loaded checkpoint IDs from the local servers;
- start and stop an agent-v-agent match;
- watch the backend-authored position, status, clocks, and trace stream;
- search previous matches;
- create named game folders and file new or existing matches into them;
- open and replay a completed match move by move;
- browse Match library by Agent vs agent or Positional testing; order match records chronologically and filter saved positional attempts by queue, set, engine analysis/grade, dataset, harness, model, and status, with the saved board and trace beside the selected attempt;
- filter the PostgreSQL position library by set, phase, type, side, dataset, source, theme, and puzzle rating; choose a harness and request one proposed move;
- choose Codex (training) for an individual saved position or a full training/test queue, and inspect the saved explanations, working notes, and tool calls;
- run every position in a dataset's training or test set sequentially, monitor progress, inspect saved results, and retry only failed positions within the same queue.

Match history uses a local SQLite-backed runner; the curated training/test
position library uses PostgreSQL in Docker. The UI talks only
to a typed backend API and polls authoritative snapshots while the selected agents
run in the background.

## Product boundaries

- The backend is authoritative for match state, legal moves, results, and traces.
- The frontend never chooses chess moves and exposes no human move controls.
- Public UI events summarize match progress; detailed graph execution remains in LangSmith.
- Shared model controls apply to new matches, standard single-position tests, and standard full-set queues. These local starts require a selected loaded model; loading, connection errors, empty inventories, and unavailable selections are explained beside the controls, with refresh available to check the server again. Codex (training) uses its connected Windows worker's model and reasoning effort independently of the shared selector; it does not require a loaded LM Studio or Unsloth model.
- Codex (training) runs individual positions and full training/test queues through the existing `chess_harness`, using the saved Codex sign-in and a fresh `codex exec` process per pass over stdio MCP. A Codex queue requires a connected, idle worker at creation and captures its model and reasoning effort for every position. Each position starts a sequential session using its existing saved queue run id, with normal exchanges and grades. The single-position UI shows worker readiness, model and effort, pass progress, and Stop Codex, and reattaches only to single-position jobs after reload. Runs do not automatically export JSONL. Setup and recovery details are in [docs/codex-mcp.md](docs/codex-mcp.md).
- Positional-test attempts and per-pass working notes/tool results persist in PostgreSQL. They do not create a match record or mutate the saved PGN. Successful Stockfish evaluations record an expected-points-loss classification and all strictly better legal moves for future training. Grading failures retain the model trace and error; existing runs are not backfilled.
- New standard positional passes also persist the actual provider request and raw response before validation. Codex passes retain the exact harness input, teacher prompt, submitted response, and authored `reasoning_text` explanation in the same run history and exchange viewer. These explanations are authored training content, not captured private reasoning; the teacher's under-1,500-token instruction is prompt guidance rather than a hard tokenizer cap. Expand leaves the pass summary intact and opens a Markdown reading view of Input and Output with a sticky Back arrow. Back, browser Back, or Escape returns to the same pass with its selection, filters, scroll, and focus preserved. Presentation does not change the saved exchange. Historical passes without captured input/output cannot be expanded.
- Full-set queues capture their dataset, split, harness, model selection (including the selected local checkpoint or Codex worker model and reasoning effort), and position membership when created, regardless of library filters. One queue runs at a time, completing each model turn and evaluation before the next position. Execution, validation, evaluation, and timeout failures are flagged in PostgreSQL and the queue continues. Pending Codex positions wait while the Windows worker is offline. Closing the browser does not stop a queue; a backend restart resumes pending positions when the required worker is available without replaying interrupted attempts.
- Training and test queues can have an optional name for organization. Names appear in queue progress, recent queues, run history, and Match Library filters/search; the queue UUID remains its identity, including when names are reused.
- **Retry a past queue:** choose a finished or stopped queue with failures independently of the displayed results. Retry failed positions reopens that same queue with its original name, ID, order, and saved harness/model settings. Failed entries get fresh attempts from the beginning through grading; completed and skipped entries stay in place. Prior traces remain in run history. Active queues and busy/offline Codex workers block retries. Codex uses the saved model and effort independently of the sidebar.
- The first release stays deliberately small: no authentication, tournaments, agent configuration editor, or trace mutation.
- Harness selections are versioned identifiers, not editable prompts.
- Stopping a match ends the active local match. Stopping any queue, including Codex, lets the current position finish and marks the remaining positions skipped; saved results remain available. Stop Codex terminates an active single-position investigation and child process while retaining saved passes; a validated move already being graded may finish grading. An active Codex session does not resume after a backend restart; pending queue positions can continue as new sessions.

## Information contract

The frontend needs nine backend-facing resources:

1. **Harness versions** — stable id, display name, version, and short description.
2. **Game folders** — stable id, user-defined name, and match count for durable organization.
3. **Match summary** — id, folder, players, status, result, timestamps, current FEN, move count, and last move.
4. **Match detail** — the summary plus chronological positions/moves and structured trace events.
5. **Match commands and updates** — start, stop, folder assignment, and polled snapshots with a possible future server-sent event stream.
6. **Positional tests** — PostgreSQL exercise summaries with visible/filterable classifiers, a one-turn command, and saved attempts with the selected harness, resolved model, proposed legal move, emitted notes/tool results, and evaluation. Engine references and exercise classifications stay out of model inputs.
7. **Full-set queues** — start/stop/retry-failed commands and durable snapshots containing captured configuration, progress counts, ordered position statuses, failure details, and links to saved attempts. Retrying reopens the same queue and replaces only failed entries; prior attempts and passes remain in run history, linked by `retry_of_run_id` and `superseded_by_run_id`. Counts and queue positions show current attempts only.
8. **Loaded models** — the selected local server and its loaded checkpoint IDs, with refresh and explicit error handling so runs use an available model.
9. **Codex worker and jobs** — worker readiness, model, reasoning effort, active run id, and nullable `active_queue_id`; start/stop commands and polled job snapshots containing position/run ids, nullable `queue_tag`, status, pass number, progress, stopping state, errors, and the normal positional-test result. Queue identifiers distinguish queue work from single-position reattachment. These resources support one worker and one active Codex session at a time across single runs and queues.

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
