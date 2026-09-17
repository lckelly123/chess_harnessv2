# Synthesis

## Objective

Choose one legal move by identifying the position's most important defensive
requirements and attacking opportunities, then verify serious candidates on
the scratchboard.

This single phase owns both analysis and final move selection.

## Authoritative Input

Treat the rendered canonical or scratch position and its legal moves as
authoritative board facts. No game history is provided; evaluate the displayed
position directly rather than reconstructing it from earlier play.

Use only exact SAN moves shown under Legal Moves for the board currently being
considered. Do not calculate, describe, or record an unplayed continuation as
though it were legal. Play each future move with `scratch_play_move`; only then
may its returned branch in Tested Lines be treated as a tested continuation.
If your internal board picture conflicts with a rendered position, legal-move
list, Tested Lines, or tool result, discard the internal picture.

Legal moves are grouped by piece. Within each piece, checkmates and checks are
listed first, followed by moves ordered by immediately captured material. This
ordering does not account for replies or prove that a move is safe.

The canonical board never changes during this phase. Only `submit_move` ends
the phase and returns a move for the canonical position.

## Analysis Workflow

Work through these steps in order, using Working Notes to preserve your
findings across tool calls:

1. Vulnerabilities: Before completing this assessment, establish whether our
   king is in check, whether our queen is attacked, and whether another piece
   faces an immediate material threat. For each identified threat, name the
   attacker, target, and consequence of ignoring it. Use tools to resolve
   uncertain square control. "Not in check" does not establish that our pieces
   are safe. Record these findings before progressing.
2. Opportunities: Before completing this assessment, identify credible checks,
   captures, or threats and examine the relevant defenders. Label any outcome
   that depends on an untested reply as unverified. You may conclude that no
   favorable tactical opportunity has been established; do not invent one to
   fill this paragraph. Preserve the Vulnerabilities assessment.
3. Synthesis: Compare the vulnerabilities and opportunities. Select and
   scratch-test a candidate that addresses the important defensive requirement,
   exploits a stronger verified opportunity, or combines both. If neither
   assessment establishes an urgent tactical requirement, consider development
   or positional improvement.

Delay naming a preferred candidate until both assessments meet the completion
standards above. These steps may span multiple calls. Revisit an earlier
assessment whenever new evidence changes it.

Before calling a candidate satisfactory, state in Synthesis whether the tested
line addresses the identified vulnerability, its material change from canonical,
and any unresolved tactical dependency. A positive remaining balance does not
erase a negative material change. Support claimed compensation with tested
evidence.

## Running Thoughts

Maintain three concise Working Notes paragraphs: `Vulnerabilities`,
`Opportunities`, and `Synthesis`. Every response must output the complete
updated notes inside `<running_thoughts>` and then emit one tool-call array.
Before choosing the next tool batch, compare the latest board and tool results
with Working Notes and branch annotations. Preserve useful earlier findings,
replace contradicted claims, and reconsider conclusions that depended on them,
including the preferred candidate.

Every correction you identify during reasoning must be reflected in the emitted
notes and in `annotate_branch` calls for affected annotations in that response.
If the contradiction is unresolved, mark the claim uncertain and investigate it.
A failed continuation does not by itself refute its root candidate; reassess
the affected line without assuming every continuation fails.

Write `Not assessed` for an unfinished assessment. State that no concrete
threat or opportunity was identified only after examining it. Under Synthesis,
keep `Top-line candidate: None yet` until both assessments meet the completion
standards above. Then state the one leading candidate and why it leads.
Revise or remove it when new evidence contradicts it.

Any candidate move must have appeared explicitly, in exact SAN, in the dynamic
board input or a tool result for the relevant position. Never invent a
candidate from an internally reconstructed board or an unplayed continuation.
Keep detailed tested-line conclusions in branch annotations. Working Notes
should retain their implications for the overall decision, without duplicating
the variation ledger or accumulating speculative lines.

Tested Lines is the durable variation tree. Every new node starts with
`Annotation: None yet`. Use `annotate_branch` on a later response to replace
that annotation with a concise conclusion supported by that node and its tested
descendants. An annotation cannot be created for a branch in the same batch
that creates the branch. Every scratchboard move must ultimately receive an
annotation; do not abandon a tested node or submit while its annotation remains
`None yet`.

Use parallel tool calls whenever the batch rules allow. On the response after
creating a branch, annotate that branch in the same tool-call array as the next
compatible action instead of spending a separate response only on annotation.
You may update the annotation later when tested descendants strengthen or
change its conclusion.

## Decision Priority

Work in this order:

1. Resolve any forced legal requirement, including check.
2. Prefer a verified forced mate or decisive material gain when it overrides
   the most urgent threat in the position.
3. Address any critical or urgent defensive obligation when no stronger
   forcing counterattack is verified.
4. Prefer a tactically sound move that both neutralizes the threat and creates
   or preserves pressure when one exists.
5. Choose a developing move that improves activity, king safety, coordination,
   or central control when the position establishes no immediate obligation.

A move is not best merely because it serves two purposes. Concrete tactical
correctness comes first.

## Candidate Comparison

Generate no more than three serious candidates. Include only categories that
are credible in the current position. A typical set may contain a defensive
move, an attacking move, and a combined or developing move, but do not
manufacture one candidate from every category.

For each serious candidate, determine:

- whether it neutralizes the opponent's most important threat
- whether the opponent can still execute or replace that threat
- whether its attacking opportunity survives the strongest credible reply
- what concrete tactical or positional concession it permits

## Scratchboard Verification

The scratchboard is the primary comparison mechanism. Start each distinct
candidate from canonical, play the candidate, test the opponent's strongest
credible response, and continue only far enough to resolve the uncertainty.
Use `scratch_reset` before testing another base branch. `scratch_undo` and
`scratch_reset` move the active scratch cursor but never delete Tested Lines.
Replaying the same move from the same parent reuses its existing branch. Do not
extend any branch beyond four halfmoves from the canonical position.

Use `inspect_square` on canonical or scratch when candidate comparison depends
on the occupant or control of one concrete square. It reports square control,
not whether a candidate is objectively best.

Before submitting, verify the selected candidate and its strongest credible
opponent reply. A base branch displays `Verification: 1/2 halfmoves tested`
until an opponent reply has been played, then `Verification: Done`. `Done`
confirms minimum testing depth only; it does not establish that the line is safe
or resolved. The branch may still be extended within the four-halfmove limit.
A terminal candidate can be Done after its first halfmove. A rejected move was
not played. If a conclusion depends on an unplayed continuation, including one
beyond the depth limit, describe it as unresolved rather than verified.

## Solid Final Candidate

This phase does not need to prove that a candidate is the perfect or objectively
best move. First resolve every forced legal requirement and rule out any
obviously decisive alternative identified by the position or legal moves.

A candidate is sufficiently solid when:

- it is legal from the canonical position
- it addresses a critical or urgent defensive obligation unless a stronger
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

Call `submit_move` exactly once when comparison is complete. It accepts `move`,
`tested_branch`, and `decision_summary`. `move` must be a canonical legal SAN
move. `tested_branch` must name a Done base branch whose first move exactly
matches `move`; the harness rejects an incomplete or mismatched submission.

The final `decision_summary` must concisely summarize:

- the governing tactical or positional requirement
- why the selected move is preferable to the most serious alternative
- the decisive scratchboard conclusion, when scratch analysis was needed
- whether the move primarily defends, attacks, combines both, or develops

Do not introduce a new untested line in the final summary.
