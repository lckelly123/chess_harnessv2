## Tool Call Format

Tool calls are parsed from plain text. You may reason before calling a tool,
but every response must end with exactly one tagged tool-call block:

<agent_tool_call>
{"tool":"inspect_square","arguments":{"board":"canonical","square":"e4","justification":"Verify control of the central square."}}
</agent_tool_call>

The tagged block must contain valid JSON with exactly one `tool` name and its
`arguments`. Output nothing after the closing tag.

## `scratch_play_move`

### Purpose

Play one legal SAN move on the scratchboard to test a concrete continuation.
This changes only the scratchboard, never the canonical position.

### Schema

```yaml
move: legal SAN move from the current scratchboard position
justification: brief explanation of the uncertainty being tested
```

## `scratch_undo`

### Purpose

Undo the most recent scratchboard move while preserving the earlier moves in
that branch.

### Schema

```yaml
justification: brief explanation of why the last move should be undone
```

## `scratch_reset`

### Purpose

Reset the scratchboard to the canonical position before testing a different
branch.

### Schema

```yaml
justification: brief explanation of why a new branch is needed
```

## `inspect_square`

### Purpose

Inspect the occupant and both sides' control of one square on either the
canonical board or scratchboard. Use it when a tactical conclusion depends on
an exact square.

This tool reports board facts; it does not determine whether a move is best.

### Schema

```yaml
board: canonical | scratch
square: chess square matching [a-h][1-8]
justification: brief explanation of the uncertainty being resolved
```

## `submit_attack_report`

### Purpose

Submit the final attacking report and end Phase 2. Use this only when the
attacking review is complete.

### Schema

```yaml
report: string
```

### Requirements

- one paragraph with no line breaks
- 40-1200 characters
- begins with exactly one of:
  - `Opportunity: Decisive.`
  - `Opportunity: Strong.`
  - `Opportunity: Practical.`
  - `Opportunity: None.`
