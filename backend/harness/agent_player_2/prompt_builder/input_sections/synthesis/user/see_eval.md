{% if hypothetical_pass %}
# Opponent Forcing Moves If {{ agent_side }} Passes ({{ board_label }})
{% elif actor_role == "agent" %}
# Agent Forcing Moves ({{ board_label }})
{% else %}
# Opponent Forcing Moves ({{ board_label }})
{% endif %}

Moving side: {{ actor }} ({{ actor_role }}). {% if hypothetical_pass %}This scan assumes {{ agent_side }} passes and gives {{ actor }} the move.{% else %}This scan uses the side to move on the {{ board_name }}.{% endif %}

Moves use SAN. After `:`, a capture shows its local SEE exchange sequence on the destination square. Outcome scores are always from {{ agent_side }}'s perspective: positive favors {{ agent_side }}, negative favors {{ opponent_side }}, and `100 cp` equals one pawn.

{% if actor_role == "opponent" %}Opponent captures with a non-negative outcome are marked `SEE-cleared locally`; checks still require review for non-material consequences.{% endif %}

{% if status == "in_check" %}
Status: Deferred. The agent is currently in check, so it cannot legally pass and the opponent's checks and captures were not generated.
{% elif status == "game_over" %}
Status: Unavailable. Game over: {{ reason }}.
{% else %}
## Checks

{% if checks %}
{% for move in checks %}
- `{{ move.san }}`{% if move.agent_score_cp is not none %}: `{{ move.exchange_sequence | join(" ") }}` | Outcome for {{ agent_side }}: `{% if move.agent_score_cp > 0 %}+{% endif %}{{ move.agent_score_cp }} cp`{% endif %}
{% endfor %}
{% else %}
None.
{% endif %}

## Non-Checking Captures

{% if captures %}
{% for move in captures %}
- `{{ move.san }}`: `{{ move.exchange_sequence | join(" ") }}` | Outcome for {{ agent_side }}: `{% if move.agent_score_cp > 0 %}+{% endif %}{{ move.agent_score_cp }} cp`{% if actor_role == "opponent" and move.agent_score_cp >= 0 %} | `SEE-cleared locally`{% endif %}
{% endfor %}
{% else %}
None.
{% endif %}
{% endif %}
