# SEE Evaluation

Moves use SAN and are legal from the canonical position with {{ see_eval.actor }} (the agent) to move. After `:`, a capturing move shows its local SEE exchange sequence on the destination square. The final value is material from the agent's perspective in centipawns (`100 cp` = one pawn): positive is a gain and negative is a loss.

{% if see_eval.status == "game_over" %}
Status: Unavailable. Game over: {{ see_eval.reason }}.
{% else %}
## Checks

{% if see_eval.checks %}
{% for move in see_eval.checks %}
- `{{ move.san }}`{% if move.agent_score_cp is not none %}: `{{ move.exchange_sequence | join(" ") }}` | `{% if move.agent_score_cp > 0 %}+{% endif %}{{ move.agent_score_cp }} cp`{% endif %}
{% endfor %}
{% else %}
None.
{% endif %}

## Captures

{% if see_eval.captures %}
{% for move in see_eval.captures %}
- `{{ move.san }}`: `{{ move.exchange_sequence | join(" ") }}` | `{% if move.agent_score_cp > 0 %}+{% endif %}{{ move.agent_score_cp }} cp`
{% endfor %}
{% else %}
None.
{% endif %}
{% endif %}
