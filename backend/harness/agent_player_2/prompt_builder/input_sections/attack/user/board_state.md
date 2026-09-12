# {{ board_label }}

Position ID: {{ position_id }}
Agent: {{ agent_side }}
Side to move: {{ side_to_move }}
Check status: {{ side_to_move }} is {% if check_status == "Yes" %}in check{% else %}not in check{% endif %}
Castling: {{ castling_rights }}
En passant: {{ en_passant }}
Draw claim available: {{ draw_claim_available }}

{% if include_scratch_moves %}
Scratchboard line: {{ scratch_moves | join(" ") }}

{% endif %}
Material:
{{ agent_side }}: {{ agent_material_cp }} material cp
{{ opponent_side }}: {{ opponent_material_cp }} material cp
Balance for {{ agent_side }}: {{ agent_material_balance }} material cp
{% if include_scratch_moves -%}
Change from canonical for {{ agent_side }}: {{ agent_material_change_from_canonical }} material cp
{% endif %}

## Pieces

{{ agent_side }}:
{% for group in agent_piece_groups -%}
{{ group.name }}: {% if group.pieces %}{% for piece in group.pieces %}{{ piece.square }}{% if not loop.last %}, {% endif %}{% endfor %}{% else %}none{% endif %}
{% endfor %}

{{ opponent_side }}:
{% for group in opponent_piece_groups -%}
{{ group.name }}: {% if group.pieces %}{% for piece in group.pieces %}{{ piece.square }}{% if not loop.last %}, {% endif %}{% endfor %}{% else %}none{% endif %}
{% endfor %}

## Legal Moves for {{ side_to_move }}

{% for group in side_to_move_piece_groups -%}
{% for piece in group.pieces -%}
{{ group.piece_name }} {{ piece.square }}: {% if piece.legal_moves %}{{ piece.legal_moves | join(", ") }}{% else %}none{% endif %}
{% endfor -%}
{% endfor %}
