# Chess Harness v2

## Product

Chess Harness v2 is a local, developer-facing observability console for autonomous chess agents. It exists to make agent-v-agent matches reproducible, inspectable, and easy to compare while the underlying harness is rebuilt around LangGraph.

## Audience

The primary user is the developer or researcher building the harness. They need to see what the backend decided, which harness version acted, how the position changed, and which trace events explain the move without operating the agents from the browser.

## First surface

The first release is a React web interface served locally through Docker. It lets the user:

- select the white and black harness versions;
- start and stop an agent-v-agent match;
- watch the backend-authored position, status, clocks, and trace stream;
- search previous matches;
- open and replay a completed match move by move.

The current data source is a mock implementation. The UI talks only to a typed match API so a later HTTP and event-stream adapter can replace the mock without changing page components.

## Product boundaries

- The backend is authoritative for match state, legal moves, results, and traces.
- The frontend never chooses chess moves and exposes no human move controls.
- Mock data must be labeled as illustrative and must not imply that a real agent or LangGraph run occurred.
- The first release stays deliberately small: no authentication, tournaments, agent configuration editor, or trace mutation.
- Harness selections are versioned identifiers, not editable prompts.
- Stopping a match is the only destructive control and affects only the active mocked match.

## Information contract

The frontend needs four backend-facing resources:

1. **Harness versions** — stable id, display name, version, and short description.
2. **Match summary** — id, players, status, result, timestamps, current FEN, move count, and last move.
3. **Match detail** — the summary plus chronological positions/moves and structured trace events.
4. **Match commands and updates** — start, stop, and a future server-sent event stream that reports snapshots and trace events.

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
