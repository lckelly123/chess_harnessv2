# Phase 2: Attack

## Objective

Determine whether the agent has an immediate forcing opportunity. Identify the
strongest checks, captures, or concrete threats available from the canonical
position and investigate their most credible continuations.

This phase produces an attacking report for a later decision phase. Do not
choose or submit the final move here.

## Authoritative Input

Treat the rendered canonical or scratch position and its legal moves as
authoritative facts. No game history is provided; evaluate the displayed
position directly rather than reconstructing it from earlier play.

Legal moves are grouped by piece. Within each piece, checkmates and checks are
listed first, followed by moves ordered by immediately captured material. This
ordering does not account for replies or prove that a move is safe.

## Attacking Review

Work in this order:

1. Examine every available check before examining captures. Determine whether
   each check forces mate, material gain, displacement, or another concrete
   concession.
2. Examine captures by immediate captured value, then use the scratchboard to
   account for replies and recaptures before judging the material result.
3. Consider concrete non-capturing threats only when the position supports a
   clear target or forced consequence.
4. Use the scratchboard to test the opponent's strongest credible reply and the
   agent's continuation. Separate verified lines from untested ideas.
5. Use `inspect_square` to verify the occupant and both sides' control of a
   tactical target on canonical or scratch when that fact affects the line.

Do not extend any scratchboard branch beyond four halfmoves from the canonical
position.

Do not invent an attack when the position does not support one. It is valid to
conclude that there is no meaningful forcing opportunity.

## Solid Attacking Candidate

This phase does not need to prove that a candidate is the perfect or objectively
best move. First review the available checks and captures for an obviously
decisive alternative.

A candidate is sufficiently solid when:

- it is legal from the canonical position
- its strongest credible reply has been tested on the scratchboard
- the tested reply does not refute the move or cause an immediate tactical loss
- the agent retains a concrete gain, threat, initiative, or useful continuation
- no displayed legal forcing move is clearly stronger

Once a candidate meets these conditions, stop searching, summarize the evidence,
and call `submit_attack_report`. The synthesis phase will decide whether the
candidate should be played.

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
- explain the relevant board or scratchboard evidence and tactical consequence
- summarize the opponent's strongest credible reply
- distinguish scratchboard-tested conclusions from unverified possibilities

Do not rank all final move candidates or make the final move decision.
