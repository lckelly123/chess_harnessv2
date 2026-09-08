# Phase 3: Decision

## Objective

Choose one legal move by reconciling the Phase 1 defensive obligation with the
Phase 2 attacking opportunity. Decide whether the position calls for defense,
attack, a move that combines both purposes, or ordinary development, then
verify the serious candidates on the scratchboard.

This is the only phase that chooses and submits the final move.

## Authoritative Input

Treat the game record, canonical legal moves, and deterministic scratchboard
results as authoritative board facts. The Phase 1 Defense Report and Phase 2
Attack Report are prior-phase judgments. Use them as focused evidence, but
correct a conclusion when exact scratchboard analysis contradicts it.

The canonical board never changes during this phase. Only `submit_move` ends
the phase and returns a move for the canonical position.

## Decision Priority

Work in this order:

1. Resolve any forced legal requirement, including check.
2. Prefer a verified forced mate or decisive material gain when it overrides
   the reported defensive threat.
3. Address a Critical or Urgent defensive obligation when no stronger forcing
   counterattack is verified.
4. Prefer a tactically sound move that both neutralizes the threat and creates
   or preserves pressure when one exists.
5. Choose a developing move that improves activity, king safety, coordination,
   or central control when neither report establishes an immediate obligation.

A move is not best merely because it serves two purposes. Concrete tactical
correctness comes first.

## Candidate Comparison

Generate no more than three serious candidates. Include only categories that
are credible in the current position. A typical set may contain the strongest
defensive move, strongest attacking move, and strongest combined or developing
move, but do not manufacture one candidate from every category.

For each serious candidate, determine:

- whether it neutralizes the Phase 1 threat
- whether the opponent can still execute or replace that threat
- whether the Phase 2 opportunity survives the strongest credible reply
- what concrete tactical or positional concession it permits

## Scratchboard Verification

The scratchboard is the primary comparison mechanism. Start each distinct
candidate from canonical, play the candidate, test the opponent's strongest
credible response, and continue only far enough to resolve the uncertainty.
Use `scratch_reset` before testing another branch. Do not extend any scratchboard
branch beyond four halfmoves from the canonical position.

Use `inspect_square` on canonical or scratch when candidate comparison depends
on the occupant or control of one concrete square. It reports square control,
not whether a candidate is objectively best.

Before submitting, verify the selected candidate and its strongest credible
reply unless the position has only one legal move or a terminal forced result
is already exact. Tool History is the variation ledger; identify the candidate
and uncertainty clearly in each justification so conclusions remain usable
in later passes.

## Solid Final Candidate

This phase does not need to prove that a candidate is the perfect or objectively
best move. First resolve every forced legal requirement and rule out any
obviously decisive alternative identified by the phase reports or legal moves.

A candidate is sufficiently solid when:

- it is legal from the canonical position
- it addresses a Critical or Urgent defensive obligation unless a stronger
  forcing counterattack is verified
- its strongest credible reply has been tested on the scratchboard unless the
  result is already exact
- the tested reply does not refute the move or cause an immediate tactical loss
- comparison with the most serious alternative reveals no clear reason to
  prefer that alternative
- the move retains a concrete continuation or useful positional purpose

Once a candidate meets these conditions, stop searching and call `submit_move`.
Do not spend additional tool calls trying to prove a small or speculative
advantage over another sound candidate.

## Completion

Call `submit_move` exactly once when comparison is complete. It accepts only
`move` and `justification`, and `move` must be one of the canonical legal SAN
moves.

The final justification must concisely summarize:

- the governing conclusion from both phase reports
- why the selected move is preferable to the most serious alternative
- the decisive scratchboard conclusion, when scratch analysis was needed
- whether the move primarily defends, attacks, combines both, or develops

Do not introduce a new untested line in the final justification.
