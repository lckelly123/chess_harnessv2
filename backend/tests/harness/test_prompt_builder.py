from pathlib import Path

import yaml

from harness.agent_player_1.prompt_builder import (
    build_attack_board_state_context,
    build_attack_prompt,
    build_attack_see_eval_context,
    build_defense_board_state_context,
    build_defense_prompt,
    build_defense_see_eval_context,
    build_forced_tool_retry_context,
    build_synthesis_board_state_context,
    build_synthesis_prompt,
    build_synthesis_see_eval_context,
    build_tool_history_context,
)
from harness.agent_player_1.state import initial_state
from harness.contracts import TurnRequest


def attack_state(fen: str, pgn: str, side: str = "white"):
    state = initial_state(
        TurnRequest(game_id="prompt-builder", fen=fen, pgn=pgn, side=side)
    )
    state["phase"] = "attack"
    return state


def defense_state(fen: str, pgn: str = "*", side: str = "white"):
    return initial_state(
        TurnRequest(game_id="prompt-builder", fen=fen, pgn=pgn, side=side)
    )


def synthesis_state(
    fen: str,
    pgn: str = "*",
    side: str = "white",
    scratch_moves: tuple[str, ...] = (),
):
    state = initial_state(
        TurnRequest(game_id="prompt-builder", fen=fen, pgn=pgn, side=side)
    )
    state["phase"] = "synthesis"
    state["scratch_moves"] = list(scratch_moves)
    return state


def tool_event(index: int, *, ok: bool = True) -> dict[str, object]:
    return {
        "type": "tool_call",
        "tool": f"tool_{index}",
        "justification": f"Reason {index}",
        "arguments": {"index": index},
        "ok": ok,
        "result_summary": f"Result {index}",
    }


def test_attack_board_state_groups_every_legal_san_move() -> None:
    state = attack_state(
        "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "1. e4 d5 *",
    )

    context = build_attack_board_state_context(state)
    grouped_moves = sorted(
        move
        for group in context.agent_piece_groups
        for piece in group.pieces
        for move in piece.legal_moves
    )

    assert grouped_moves == sorted(state["legal_san"])
    assert context.moves_so_far == "1. e4 d5"
    assert context.castling_rights == "White O-O, O-O-O; Black O-O, O-O-O"

    pawns = next(group for group in context.agent_piece_groups if group.name == "Pawns")
    e4 = next(piece for piece in pawns.pieces if piece.square == "e4")
    assert e4.legal_moves == ("e5", "exd5")

    bishops = next(
        group for group in context.agent_piece_groups if group.name == "Bishops"
    )
    f1 = next(piece for piece in bishops.pieces if piece.square == "f1")
    assert "Bb5+" in f1.legal_moves


def test_attack_board_state_renders_compact_san_piece_lists() -> None:
    state = attack_state(
        "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "1. e4 d5 *",
    )

    packet = build_attack_prompt(state)

    assert "# Phase 2: Attack" in packet.instructions
    assert "## `submit_attack_report`" in packet.instructions
    assert "# Board State" in packet.dynamic_input
    assert "1. e4 d5" in packet.dynamic_input
    assert "## My Pieces" in packet.dynamic_input
    assert "- e4: `e5`, `exd5`" in packet.dynamic_input
    assert "- f1: `Ba6`, `Bb5+`, `Bc4`, `Bd3`, `Be2`" in packet.dynamic_input
    assert "`a4`\n- b2:" in packet.dynamic_input
    assert "`Ke2`\n\n## Opponent Pieces" in packet.dynamic_input
    assert "## Opponent Pieces" in packet.dynamic_input
    assert "- d5" in packet.dynamic_input


def test_attack_board_state_exposes_legal_en_passant_san() -> None:
    state = attack_state(
        "rnbqkbnr/1pp1pppp/p7/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3",
        "1. e4 a6 2. e5 d5 *",
    )

    context = build_attack_board_state_context(state)

    assert context.en_passant == "exd6"
    pawns = next(group for group in context.agent_piece_groups if group.name == "Pawns")
    e5 = next(piece for piece in pawns.pieces if piece.square == "e5")
    assert "exd6" in e5.legal_moves


def test_defense_and_synthesis_reuse_canonical_board_state() -> None:
    fen = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    pgn = "1. e4 d5 *"
    attack = attack_state(fen, pgn)
    defense = defense_state(fen, pgn)
    synthesis = defense_state(fen, pgn)
    synthesis["phase"] = "synthesis"

    attack_context = build_attack_board_state_context(attack)
    defense_context = build_defense_board_state_context(defense)
    synthesis_context = build_synthesis_board_state_context(synthesis)
    defense_packet = build_defense_prompt(defense)
    synthesis_packet = build_synthesis_prompt(synthesis)

    assert defense_context == attack_context
    assert synthesis_context == attack_context
    for packet in (defense_packet, synthesis_packet):
        assert "# Board State" in packet.dynamic_input
        assert "1. e4 d5" in packet.dynamic_input
        assert "Side to move: White" in packet.dynamic_input
        assert "- e4: `e5`, `exd5`" in packet.dynamic_input
        assert packet.dynamic_input.index("# Board State") < packet.dynamic_input.index(
            "# Tool History"
        )
    assert defense_packet.dynamic_input.index(
        "# Board State"
    ) < defense_packet.dynamic_input.index("# SEE Evaluation")


def test_attack_see_eval_reuses_exchange_sequence_and_agent_score() -> None:
    state = attack_state(
        "3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1",
        "*",
    )

    context = build_attack_see_eval_context(state)
    capture = next(move for move in context.captures if move.san == "Rxd8")
    packet = build_attack_prompt(state)

    assert capture.exchange_sequence == ("Rxd8", "Qxd8")
    assert capture.agent_score_cp == 0
    assert "# SEE Evaluation" in packet.dynamic_input
    assert "`100 cp` = one pawn" in packet.dynamic_input
    assert "- `Rxd8`: `Rxd8 Qxd8` | `0 cp`" in packet.dynamic_input


def test_attack_forced_tool_retry_is_conditional_and_preserves_reasoning() -> None:
    state = attack_state(
        "3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1",
        "*",
    )

    assert "# Forced Tool Call Retry" not in build_attack_prompt(state).dynamic_input

    state["forced_retry"] = True
    state["retry_output"] = "I should inspect d8 before continuing."
    context = build_forced_tool_retry_context(state)
    packet = build_attack_prompt(state)

    assert context.active
    assert context.previous_output == "I should inspect d8 before continuing."
    assert context.fence == "````"
    assert packet.dynamic_input.index("# Tool History") < packet.dynamic_input.index(
        "# Forced Tool Call Retry"
    )
    assert "````text\nI should inspect d8 before continuing.\n````" in packet.dynamic_input
    assert "<agent_tool_call>" in packet.dynamic_input
    assert "</agent_tool_call>" in packet.dynamic_input
    assert packet.dynamic_input.endswith("Output nothing after the closing tag.")

    state["retry_output"] = "Reasoning containing ```` must remain fenced."
    assert build_forced_tool_retry_context(state).fence == "`````"


def test_synthesis_see_eval_matches_attack_on_canonical_board() -> None:
    fen = "3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1"
    attack = attack_state(fen, "*")
    synthesis = synthesis_state(fen)

    context = build_synthesis_see_eval_context(synthesis)
    packet = build_synthesis_prompt(synthesis)

    assert context.canonical == build_attack_see_eval_context(attack)
    assert context.scratch_status == "unused"
    assert context.scratch is None
    assert "## Canonical Board" in packet.dynamic_input
    assert "Side to move: White (agent)" in packet.dynamic_input
    assert "- `Rxd8`: `Rxd8 Qxd8` | `0 cp`" in packet.dynamic_input
    assert "## Scratchboard\n\nStatus: unused" in packet.dynamic_input


def test_synthesis_scratch_see_follows_actual_actor_with_agent_scores() -> None:
    fen = "3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1"
    opponent_turn = synthesis_state(fen, scratch_moves=("Rxd8",))
    agent_turn = synthesis_state(fen, scratch_moves=("Rxd8", "Qxd8"))

    opponent_context = build_synthesis_see_eval_context(opponent_turn)
    agent_context = build_synthesis_see_eval_context(agent_turn)
    packet = build_synthesis_prompt(opponent_turn)

    assert opponent_context.scratch_status == "active"
    assert opponent_context.scratch_moves == ("Rxd8",)
    assert opponent_context.scratch is not None
    assert opponent_context.scratch.actor == "Black"
    assert opponent_context.scratch.actor_role == "opponent"
    recapture = next(
        move for move in opponent_context.scratch.captures if move.san == "Qxd8"
    )
    assert recapture.exchange_sequence == ("Qxd8",)
    assert recapture.agent_score_cp == -500
    assert "Moves from canonical: `Rxd8`" in packet.dynamic_input
    assert "Side to move: Black (opponent)" in packet.dynamic_input
    assert "- `Qxd8`: `Qxd8` | `-500 cp`" in packet.dynamic_input

    assert agent_context.scratch is not None
    assert agent_context.scratch.actor == "White"
    assert agent_context.scratch.actor_role == "agent"


def test_defense_see_eval_assumes_opponent_turn_and_uses_agent_score() -> None:
    state = defense_state("3r3k/8/8/8/8/8/K7/3Q4 w - - 0 1")

    context = build_defense_see_eval_context(state)
    capture = next(move for move in context.captures if move.san == "Rxd1")
    packet = build_defense_prompt(state)

    assert context.actor == "Black"
    assert capture.exchange_sequence == ("Rxd1",)
    assert capture.agent_score_cp == -900
    assert "assumes White (the agent) passes" in packet.dynamic_input
    assert "Black (the opponent) is given the move" in packet.dynamic_input
    assert "- `Rxd1`: `Rxd1` | `-900 cp`" in packet.dynamic_input


def test_defense_see_eval_defers_hypothetical_pass_while_in_check() -> None:
    state = defense_state("k3r3/8/8/8/8/8/3R4/4K3 w - - 0 1")

    context = build_defense_see_eval_context(state)
    packet = build_defense_prompt(state)

    assert context.status == "in_check"
    assert context.checks == ()
    assert context.captures == ()
    assert "cannot legally pass" in packet.dynamic_input
    assert "were not generated" in packet.dynamic_input


def test_tool_history_renders_last_seven_current_phase_calls_for_all_phases() -> None:
    history = [
        {"type": "model_output", "text": "not a tool call"},
        *(tool_event(index, ok=index != 9) for index in range(1, 10)),
    ]
    attack = attack_state(
        "3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1",
        "*",
    )
    defense = defense_state("3r3k/8/8/8/8/8/K7/3Q4 w - - 0 1")
    synthesis = defense_state("3r3k/8/8/8/8/8/K7/3Q4 w - - 0 1")
    synthesis["phase"] = "synthesis"

    for state in (attack, defense, synthesis):
        state["history"] = history

    context = build_tool_history_context(attack)
    packets = (
        build_attack_prompt(attack),
        build_defense_prompt(defense),
        build_synthesis_prompt(synthesis),
    )

    assert len(context.entries) == 7
    assert [entry.tool for entry in context.entries] == [
        "tool_3",
        "tool_4",
        "tool_5",
        "tool_6",
        "tool_7",
        "tool_8",
        "tool_9",
    ]
    for packet in packets:
        assert "# Tool History" in packet.dynamic_input
        assert "`tool_1`" not in packet.dynamic_input
        assert "`tool_2`" not in packet.dynamic_input
        assert "## 1. `tool_3`" in packet.dynamic_input
        assert "## 7. `tool_9`" in packet.dynamic_input
        assert '"index": 9' in packet.dynamic_input
        assert "Status: rejected" in packet.dynamic_input
        assert "Result summary: Result 9" in packet.dynamic_input


def test_v2_manifests_declare_ordered_conditional_sections() -> None:
    root = (
        Path(__file__).parents[2]
        / "harness"
        / "agent_player_1"
        / "prompt_builder"
        / "input_sections"
    )
    expected_ids = [
        "canonical_board_state",
        "canonical_see_eval",
        "scratch_board_state",
        "scratch_see_eval",
        "tool_history",
        "forced_tool_retry",
    ]

    for phase in ("defense", "attack", "synthesis"):
        manifest = yaml.safe_load(
            (root / phase / "manifest.yaml").read_text(encoding="utf-8")
        )
        system_sections, user_sections = manifest["messages"]

        assert manifest["version"] == 2
        assert manifest["phase"] == phase
        assert [section["id"] for section in system_sections["sections"]] == [
            "tool_schemas",
            "phase_instructions",
        ]
        assert [section["id"] for section in user_sections["sections"]] == expected_ids
        assert user_sections["sections"][2]["when"] == {
            "field": "scratch.status",
            "equals": "active",
        }
        assert user_sections["sections"][3]["when"] == {
            "field": "scratch.status",
            "equals": "active",
        }
        assert user_sections["sections"][-1]["when"] == {
            "field": "retry.active",
            "equals": True,
        }
