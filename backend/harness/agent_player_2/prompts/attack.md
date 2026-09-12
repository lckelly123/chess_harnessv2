# Phase 2: Attack

## Objective

Determine whether the agent has an immediate forcing opportunity. Identify the
strongest checks, captures, or concrete threats available from the canonical
position and investigate their most credible continuations.

This phase produces an attacking report for a later decision phase. Do not
choose or submit the final move here.

## Authoritative Input

Treat the game record, Agent Forcing-Move Scan, and scratchboard results as
authoritative facts.

The forcing scan uses the real canonical position with the agent to move. It
lists legal checks first, followed by legal non-checking captures. A capturing
check appears only under Checks.

SEE is a local material calculation for captures and recaptures on one target
square. Its sequence is not a complete tactical line, particularly when the
initial capture gives check. Non-capturing checks have no SEE result. Use SEE
as evidence about material risk, not as proof that a move is best or harmless.

The scan is tactical triage, not a complete move list. A strong non-capturing
threat may be considered when it is visible from the position, but do not claim
that it is forcing without testing its most credible defensive reply.

## Attacking Review

Work in this order:

1. Examine every available check before examining captures. Determine whether
   each check forces mate, material gain, displacement, or another concrete
   concession.
2. Examine captures in order of agent material gain. Account for the complete
   displayed SEE sequence and whether a larger tactical consequence overrides
   the local exchange result.
3. Consider concrete non-capturing threats only when the position supports a
   clear target or forced consequence.
4. Use the scratchboard to test the opponent's strongest credible reply and the
   agent's continuation. Separate verified lines from untested ideas.
5. Use `inspect_square` to verify the occupant and both sides' control of a
   tactical target on canonical or scratch when that fact affects the line.

Do not invent an attack when the scan and position do not support one. It is
valid to conclude that there is no meaningful forcing opportunity.

## Completion

When the attacking review is complete, call `submit_attack_report` with one
concise paragraph. Begin with exactly one of: `Opportunity: Decisive.`,
`Opportunity: Strong.`, `Opportunity: Practical.`, or `Opportunity: None.`

- `Decisive` means forced mate or decisive material gain is verified.
- `Strong` means a concrete favorable forcing continuation is verified.
- `Practical` means a move creates meaningful pressure, but no forced gain is
  verified.
- `None` means no meaningful forcing opportunity was found.

The paragraph must:

- identify the strongest checks, captures, or concrete threats
- explain the relevant SEE evidence and tactical consequence
- summarize the opponent's strongest credible reply
- distinguish scratchboard-tested conclusions from unverified possibilities

Do not rank all final move candidates or make the final move decision.
