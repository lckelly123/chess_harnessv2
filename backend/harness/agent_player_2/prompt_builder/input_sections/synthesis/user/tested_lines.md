# Tested Lines

Material change is cumulative from the canonical position and uses the
Agent ({{ agent_side }}) perspective.

{% if entries %}
{% for entry in entries %}
{{ entry.heading }} Branch {{ entry.branch_id }}

Ply {{ entry.ply }} | {{ entry.actor_label }} | {{ entry.move }}
Material change: {{ entry.material_change }} cp
Annotation: {{ entry.annotation }}
{% if entry.verification %}
Verification: {{ entry.verification }}
{% endif %}

{% endfor %}
{% else %}
No tested lines yet.
{% endif %}
