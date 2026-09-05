---
name: agent-player-1
description: Shared contract for the three-phase Agent Player 1 chess harness.
---

# Agent Player 1

Agent Player 1 is being rebuilt as a three-phase move-selection system.

The harness owns deterministic board state, legal move validation, tool
execution, phase transitions, and turn-local state. The model remains
responsible for chess judgment.

## Scratchboard Depth Limit

Use the scratchboard to verify concrete candidate lines, not to search
indefinitely. Limit each scratchboard branch to four halfmoves from the
canonical position. A halfmove is one move by either side, so this usually
means the candidate move, the strongest credible reply, and no more than two
continuation moves.

When a branch reaches four halfmoves, stop extending it and summarize what the
line proved for the current phase. Use `scratch_reset` before testing a
different branch from the canonical position.

## Reasoning Budget and Forced-Action Fallback

Each phase has a 2000-token reasoning budget for any pass that does not call a
tool. If a pass uses that budget without calling a tool, the harness ends that
pass and reruns the same phase through LM Studio with reasoning disabled.

The fallback pass receives the complete visible output from the exhausted pass,
then a final instruction requiring one available tool call. Treat that previous
output as context only. In fallback mode, do not continue analysis; call exactly
one available tool using the current dynamic input, Tool History, and previous
exhausted output.

At runtime, compose this shared contract with exactly one phase file:

- `phases/01_defense/PHASE.md`
- `phases/02_attack/PHASE.md`
- `phases/03_decision/PHASE.md`

Do not load multiple phase files into the same model request. Phase 1 is an
independently runnable defensive report phase. Phase 2 is an independently
runnable attacking report phase from the same canonical position. Phase 3 is an
independently runnable final decision phase that consumes both independent
reports and submits one legal move. The harness orchestrates these phases in
that order while keeping their model contexts separate.
