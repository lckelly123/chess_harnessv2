# Board State

## Moves So Far

```pgn
{{ moves_so_far }}
```

## Piece Info

Side to move: {{ side_to_move }}
Check: {{ check_status }}
Castling rights: {{ castling_rights }}
En passant: {{ en_passant }}

## My Pieces

{% for group in agent_piece_groups %}
### {{ group.name }}

{% if group.pieces %}
{% for piece in group.pieces %}
- {{ piece.square }}: {% if piece.legal_moves %}{% for move in piece.legal_moves %}`{{ move }}`{% if not loop.last %}, {% endif %}{% endfor %}{% else %}none{% endif %}
{% endfor %}
{% else %}
None.
{% endif %}
{% endfor %}
## Opponent Pieces

{% for group in opponent_piece_groups %}
### {{ group.name }}

{% if group.pieces %}
{% for piece in group.pieces %}
- {{ piece.square }}
{% endfor %}
{% else %}
None.
{% endif %}
{% endfor %}
