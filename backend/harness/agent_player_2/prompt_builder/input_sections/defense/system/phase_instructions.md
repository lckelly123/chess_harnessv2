# Phase 1: Defense

## Objective

Determine whether the current position creates an immediate defensive
obligation. Identify the opponent's most forcing move or moves, judge their
severity, and investigate credible ways to respond.

This phase produces a defensive report for a later decision phase. Do not
choose or submit the final move here.

## Authoritative Input

Treat the rendered canonical or scratch position and its legal moves as
authoritative board facts. No game history is provided; evaluate the displayed
position directly rather than reconstructing it from earlier play.

Legal moves are grouped by piece. Within each piece, checkmates and checks are
listed first, followed by moves ordered by immediately captured material. This
ordering does not account for replies or prove that a move is safe.

## Canonical Position vs Scratchboard

The scratchboard always starts from the canonical position with the agent to
move.

To test a defensive response, first play the agent's candidate response on the
scratchboard. Then test whether the opponent's strongest credible forcing
continuation is legal, stronger, weaker, or neutralized.

Do not extend any scratchboard branch beyond four halfmoves from the canonical
position.

## Defensive Review

Work in this order:

1. If Check status says the agent is in check, resolving it is mandatory.
   Consider only the displayed legal evasions. A counterattack matters only if
   it also resolves the check.
2. Otherwise, identify the opponent's immediate checks and captures from the
   rendered position. Determine whether they create mate, material loss,
   displacement, or another concrete consequence.
3. Prioritize threats against higher-value material, then use the scratchboard
   to account for replies and recaptures before judging the material result.
4. Identify practical response types: move the target, capture or deflect the
   attacker, add protection, interpose, simplify, or create stronger forcing
   counterplay.
5. Use the scratchboard when a response or continuation must be tested on an
   exact board. Verify that the opponent cannot still execute the original
   threat or replace it with something stronger.
6. Use `inspect_square` when exact control of a threatened, capture, or blocking
   square is unclear. Choose canonical or scratch explicitly.

Do not invent an urgent threat when the position does not support one. It is
valid to conclude that there is no immediate defensive obligation.

## Solid Defensive Response

This phase does not need to prove that a response is the perfect or objectively
best move. First review the current check and available opponent checks and
captures for an obviously critical threat.

A response is sufficiently solid when:

- it is legal from the canonical position
- it resolves the current check when one is active
- the opponent's strongest credible continuation has been tested on the
  scratchboard
- the tested continuation no longer produces the original critical or urgent
  consequence
- the response does not permit an immediate tactical loss or equally serious
  replacement threat
- no concrete forcing threat clearly remains unaddressed

Once a response meets these conditions, stop searching, summarize the evidence,
and call `submit_defense_report`. If there is no immediate defensive obligation,
report `Severity: None.` without inventing or testing a defensive response. The
synthesis phase will decide whether a candidate response should be played.

## Completion

When the defensive review is complete, call `submit_defense_report` with one
concise paragraph. Begin with exactly one of: `Severity: Critical.`,
`Severity: Urgent.`, `Severity: Manageable.`, or `Severity: None.`

- `Critical` means checkmate or decisive material loss is immediately forced.
- `Urgent` means a concrete threat requires an immediate response.
- `Manageable` means a real threat exists but several viable responses or
  acceptable outcomes remain.
- `None` means no immediate defensive obligation was found.

The paragraph must:

- identify the most important opponent move or moves
- explain the concrete consequence and relevant board or scratchboard evidence
- state whether an immediate response is required
- name the most credible response types or tested moves
- distinguish scratchboard-tested conclusions from unverified possibilities

Do not rank the agent's final move candidates or make the final move decision.
