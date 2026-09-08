{% macro render_scan(scan) %}
{% if scan.status == "game_over" %}
Status: Unavailable. Game over: {{ scan.reason }}.
{% else %}
### Checks

{% if scan.checks %}
{% for move in scan.checks %}
- `{{ move.san }}`{% if move.agent_score_cp is not none %}: `{{ move.exchange_sequence | join(" ") }}` | `{% if move.agent_score_cp > 0 %}+{% endif %}{{ move.agent_score_cp }} cp`{% endif %}
{% endfor %}
{% else %}
None.
{% endif %}

### Captures

{% if scan.captures %}
{% for move in scan.captures %}
- `{{ move.san }}`: `{{ move.exchange_sequence | join(" ") }}` | `{% if move.agent_score_cp > 0 %}+{% endif %}{{ move.agent_score_cp }} cp`
{% endfor %}
{% else %}
None.
{% endif %}
{% endif %}
{% endmacro %}
# SEE Evaluation

Each board is scanned for checks and non-checking captures available to its side to move. Moves use SAN. After `:`, a capturing move shows its local SEE exchange sequence on the destination square. Values are always from the agent's perspective in centipawns (`100 cp` = one pawn): positive is an agent gain and negative is an agent loss.

## Canonical Board

Side to move: {{ see_eval.canonical.actor }} ({{ see_eval.canonical.actor_role }})

{{ render_scan(see_eval.canonical) }}

## Scratchboard

{% if see_eval.scratch_status == "unused" %}
Status: unused
{% else %}
Status: active
Moves from canonical: `{{ see_eval.scratch_moves | join(" ") }}`
Side to move: {{ see_eval.scratch.actor }} ({{ see_eval.scratch.actor_role }})

{{ render_scan(see_eval.scratch) }}
{% endif %}
