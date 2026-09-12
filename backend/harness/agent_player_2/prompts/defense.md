# Phase 1: Defense

## Objective

Determine whether the current position creates an immediate defensive
obligation. Identify the opponent's most forcing move or moves, judge their
severity, and investigate credible ways to respond.

This phase produces a defensive report for a later decision phase. Do not
choose or submit the final move here.

## Authoritative Input

Treat the game record, Current Check section, Opponent Forcing-Move Scan, and
scratchboard results as authoritative board facts.

The forcing scan assumes the agent passes and the opponent is given the move.
It lists legal checks first, followed by legal non-checking captures. A
capturing check appears only under Checks.

SEE is a local material calculation for captures and recaptures on one target
square. Its sequence is not a complete tactical line, particularly when the
initial capture gives check. Non-capturing checks have no SEE result. Use SEE
as evidence about material risk, not as proof that a move is best or harmless.

## Defensive Scan vs Scratchboard

The Opponent Forcing-Move Scan is a diagnostic only. It asks: if the agent made
no move, what forcing checks or captures would the opponent have?

That pass assumption does not change the scratchboard start state. The
scratchboard always starts from the canonical position with the agent to move.

To test a defensive response, first play the agent's candidate response on the
scratchboard. Then test whether the opponent's strongest listed or related
forcing continuation is still legal, stronger, weaker, or neutralized. Do not
begin a scratchboard line by playing the opponent's scanned move unless the
scratchboard side to move actually belongs to the opponent.

## Defensive Review

Work in this order:

1. If Current Check is active, resolving it is mandatory. Consider only listed
   legal evasions. A counterattack matters only if it also resolves the check.
2. Otherwise, examine every opponent check before examining captures. Determine
   whether each check creates mate, material loss, displacement, or another
   concrete consequence.
3. Examine captures in order of agent material loss. Account for the complete
   displayed SEE sequence and whether a larger tactical consequence overrides
   the local exchange result.
4. Identify practical response types: move the target, capture or deflect the
   attacker, add protection, interpose, simplify, or create stronger forcing
   counterplay.
5. Use the scratchboard when a response or continuation must be tested on an
   exact board. Verify that the opponent cannot still execute the original
   threat or replace it with something stronger.
6. Use `inspect_square` when exact control of a threatened, capture, or blocking
   square is unclear. Choose canonical or scratch explicitly.

Do not invent an urgent threat when the scan and position do not support one.
It is valid to conclude that there is no immediate defensive obligation.

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
- explain the concrete consequence and relevant SEE evidence
- state whether an immediate response is required
- name the most credible response types or tested moves
- distinguish scratchboard-tested conclusions from unverified possibilities

Do not rank the agent's final move candidates or make the final move decision.
