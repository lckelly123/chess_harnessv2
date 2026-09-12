from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from harness.agent_player_1.prompt_builder import build_prompt
from harness.agent_player_1.prompt_builder.context import (
    build_attack_board_state_context,
    build_attack_see_eval_context,
    build_defense_board_state_context,
    build_defense_see_eval_context,
    build_forced_tool_retry_context,
    build_see_eval_context,
    build_synthesis_board_state_context,
    build_synthesis_see_eval_context,
    build_tool_history_context,
)
from harness.agent_player_1.prompt_builder.manifest import load_manifest
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
        for group in context.side_to_move_piece_groups
        for piece in group.pieces
        for move in piece.legal_moves
    )

    assert grouped_moves == sorted(state["legal_san"])
    assert context.position_id.startswith("pos-")
    assert context.castling_rights == "White KQ, Black kq"
    assert context.draw_claim_available == "no"
    assert context.agent_material_cp == 4000
    assert context.opponent_material_cp == 4000
    assert context.agent_material_balance == "+0"

    pawns = next(group for group in context.agent_piece_groups if group.name == "Pawns")
    e4 = next(piece for piece in pawns.pieces if piece.square == "e4")
    assert e4.legal_moves == ("exd5", "e5")

    bishops = next(
        group for group in context.agent_piece_groups if group.name == "Bishops"
    )
    f1 = next(piece for piece in bishops.pieces if piece.square == "f1")
    assert f1.legal_moves == ("Bb5+", "Ba6", "Bc4", "Bd3", "Be2")


def test_attack_board_state_renders_compact_san_piece_lists() -> None:
    state = attack_state(
        "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "1. e4 d5 *",
    )

    packet = build_prompt(state)

    assert "# Phase 2: Attack" in packet.instructions
    assert "## `submit_attack_report`" in packet.instructions
    assert "# Canonical Position" in packet.dynamic_input
    assert "## Move History" not in packet.dynamic_input
    assert "1. e4 d5" not in packet.dynamic_input
    assert "Agent: White" in packet.dynamic_input
    assert "White:\nKing: e1" in packet.dynamic_input
    assert "Black:\nKing: e8" in packet.dynamic_input
    assert "Pawn e4: exd5, e5" in packet.dynamic_input
    assert "Bishop f1: Bb5+, Ba6, Bc4, Bd3, Be2" in packet.dynamic_input
    assert "Pawn b2: b3, b4" in packet.dynamic_input
    assert "Forcing Moves" not in packet.dynamic_input


def test_queen_blunder_position_renders_material_and_ranked_legal_moves() -> None:
    state = defense_state(
        "2r1kb1r/p1p1pppp/2p5/8/3q4/2N1B3/PPP2PPP/R3K2R b KQk - 1 12",
        "1. e4 Nf6 2. Nf3 Nxe4 3. Qe2 Nc5 4. d4 Nca6 5. Nc3 Nc6 "
        "6. d5 Ncb4 7. Nd4 Nc6 8. Qxa6 bxa6 9. dxc6 dxc6 "
        "10. Bxa6 Qxd4 11. Bxc8 Rxc8 12. Be3 *",
        side="black",
    )

    packet = build_prompt(state)

    assert "## Move History" not in packet.dynamic_input
    assert "Black: 2930 material cp" in packet.dynamic_input
    assert "White: 2250 material cp" in packet.dynamic_input
    assert "Balance for Black: +680 material cp" in packet.dynamic_input
    assert "Castling: White KQ, Black k" in packet.dynamic_input
    assert "Bishops: e3" in packet.dynamic_input
    assert "Knights: c3" in packet.dynamic_input
    assert "Queen d4: Qxe3+, Qxc3+, Qd1+, Qd2+, Qa4" in packet.dynamic_input
    assert "Agent Forcing Moves" not in packet.dynamic_input


@pytest.mark.parametrize("phase", ["defense", "attack", "synthesis"])
def test_scratch_position_renders_material_change_from_canonical(phase: str) -> None:
    state = defense_state(
        "2r1kb1r/p1p1pppp/2p5/8/3q4/2N1B3/PPP2PPP/R3K2R b KQk - 1 12",
        side="black",
    )
    state["phase"] = phase
    state["scratch_moves"] = ["Qxe3+", "fxe3"]

    packet = build_prompt(state)

    assert "Balance for Black: +680 material cp" in packet.dynamic_input
    assert "Balance for Black: +110 material cp" in packet.dynamic_input
    assert (
        "Balance for Black: +110 material cp\n"
        "Change from canonical for Black: -570 material cp"
    ) in packet.dynamic_input
    assert "Change from canonical for Black: +0 material cp" not in packet.dynamic_input


def test_defense_prompt_distinguishes_immobile_from_absent_pieces() -> None:
    pgn = (
        "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. d3 Bc5 5. O-O O-O "
        "6. Nc3 d6 7. Re1 Bxf2+ 8. Kxf2 Ng4+ 9. Kg1 Qh4 10. Nxh4 *"
    )
    state = defense_state(
        "r1b2rk1/ppp2ppp/2np4/4p3/2B1P1nN/2NP4/PPP3PP/R1BQR1K1 b - - 0 10",
        pgn,
        side="black",
    )

    context = build_defense_board_state_context(state)
    packet = build_prompt(state)

    assert context.agent_side == "Black"
    assert context.opponent_side == "White"
    assert "## Move History" not in packet.dynamic_input
    assert "Check status: Black is not in check" in packet.dynamic_input
    assert "Black:\nKing: g8" in packet.dynamic_input
    assert "Pawn f7: none" in packet.dynamic_input
    assert "Queen: none" in packet.dynamic_input
    assert "Opponent Forcing Moves" not in packet.dynamic_input
    assert "SEE-cleared locally" not in packet.dynamic_input


def test_attack_board_state_exposes_legal_en_passant_san() -> None:
    state = attack_state(
        "rnbqkbnr/1pp1pppp/p7/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3",
        "1. e4 a6 2. e5 d5 *",
    )

    context = build_attack_board_state_context(state)

    assert context.en_passant == "d6"
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
    defense_packet = build_prompt(defense)
    synthesis_packet = build_prompt(synthesis)

    assert defense_context == attack_context
    assert synthesis_context == attack_context
    for packet in (defense_packet, synthesis_packet):
        assert "# Canonical Position" in packet.dynamic_input
        assert "1. e4 d5" not in packet.dynamic_input
        assert "Side to move: White" in packet.dynamic_input
        assert "Pawn e4: exd5, e5" in packet.dynamic_input
        assert packet.dynamic_input.index(
            "# Canonical Position"
        ) < packet.dynamic_input.index("# Tool History")
        assert "Forcing Moves" not in packet.dynamic_input


def test_attack_see_eval_reuses_exchange_sequence_and_agent_score() -> None:
    state = attack_state(
        "3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1",
        "*",
    )

    context = build_attack_see_eval_context(state)
    capture = next(move for move in context.captures if move.san == "Rxd8")
    packet = build_prompt(state)

    assert capture.exchange_sequence == ("Rxd8", "Qxd8")
    assert capture.agent_score_cp == 0
    assert "# Agent Forcing Moves (Canonical Board)" not in packet.dynamic_input
    assert "`100 cp` equals one pawn" not in packet.dynamic_input


def test_attack_forced_tool_retry_is_conditional_and_preserves_reasoning() -> None:
    state = attack_state(
        "3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1",
        "*",
    )

    assert "# Forced Tool Call Retry" not in build_prompt(state).dynamic_input

    state["forced_retry"] = True
    state["retry_output"] = "I should inspect d8 before continuing."
    context = build_forced_tool_retry_context(state)
    packet = build_prompt(state)

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


def test_synthesis_includes_prior_reports_in_manifest_order() -> None:
    state = synthesis_state(
        "3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1",
    )
    state["defense_report"] = "Defense evidence."
    state["attack_report"] = "Attack evidence."

    packet = build_prompt(state)

    assert "# Prior Phase Reports" in packet.dynamic_input
    assert "Defense evidence." in packet.dynamic_input
    assert "Attack evidence." in packet.dynamic_input
    assert packet.dynamic_input.index(
        "# Canonical Position"
    ) < packet.dynamic_input.index("# Prior Phase Reports")
    assert packet.dynamic_input.index(
        "# Prior Phase Reports"
    ) < packet.dynamic_input.index("# Tool History")


def test_synthesis_see_eval_matches_attack_and_omits_inactive_scratch() -> None:
    fen = "3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1"
    attack = attack_state(fen, "*")
    synthesis = synthesis_state(fen)

    context = build_synthesis_see_eval_context(synthesis)
    packet = build_prompt(synthesis)

    assert context == build_attack_see_eval_context(attack)
    assert "# Agent Forcing Moves (Canonical Board)" not in packet.dynamic_input
    assert "Outcome for White" not in packet.dynamic_input
    assert "# Scratch Position" not in packet.dynamic_input
    assert "Forcing Moves (Scratchboard)" not in packet.dynamic_input


def test_synthesis_scratch_see_follows_actual_actor_with_agent_scores() -> None:
    fen = "3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1"
    opponent_turn = synthesis_state(fen, scratch_moves=("Rxd8",))
    agent_turn = synthesis_state(fen, scratch_moves=("Rxd8", "Qxd8"))

    opponent_context = build_see_eval_context(
        opponent_turn,
        source="scratch",
        actor="side_to_move",
        score_perspective="agent",
    )
    agent_context = build_see_eval_context(
        agent_turn,
        source="scratch",
        actor="side_to_move",
        score_perspective="agent",
    )
    packet = build_prompt(opponent_turn)

    assert opponent_context.actor == "Black"
    assert opponent_context.actor_role == "opponent"
    recapture = next(move for move in opponent_context.captures if move.san == "Qxd8")
    assert recapture.exchange_sequence == ("Qxd8",)
    assert recapture.agent_score_cp == -500
    assert "# Scratch Position" in packet.dynamic_input
    assert "Scratchboard line: Rxd8" in packet.dynamic_input
    assert "Side to move: Black" in packet.dynamic_input
    assert "Queen e8: Qxd8, Qf8" in packet.dynamic_input
    assert "# Opponent Forcing Moves (Scratchboard)" not in packet.dynamic_input
    assert "Outcome for White" not in packet.dynamic_input

    assert agent_context.actor == "White"
    assert agent_context.actor_role == "agent"


def test_defense_see_eval_assumes_opponent_turn_and_uses_agent_score() -> None:
    state = defense_state("3r3k/8/8/8/8/8/K7/3Q4 w - - 0 1")

    context = build_defense_see_eval_context(state)
    capture = next(move for move in context.captures if move.san == "Rxd1")
    packet = build_prompt(state)

    assert context.actor == "Black"
    assert capture.exchange_sequence == ("Rxd1",)
    assert capture.agent_score_cp == -900
    assert "# Opponent Forcing Moves If White Passes" not in packet.dynamic_input
    assert "Outcome for White" not in packet.dynamic_input


def test_defense_see_eval_defers_hypothetical_pass_while_in_check() -> None:
    state = defense_state("k3r3/8/8/8/8/8/3R4/4K3 w - - 0 1")

    context = build_defense_see_eval_context(state)
    packet = build_prompt(state)

    assert context.status == "in_check"
    assert context.checks == ()
    assert context.captures == ()
    assert "Opponent Forcing Moves" not in packet.dynamic_input


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
        build_prompt(attack),
        build_prompt(defense),
        build_prompt(synthesis),
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


def test_manifest_validates_inactive_providers_up_front() -> None:
    manifest = """\
version: 2
phase: attack
messages:
  - role: system
    sections:
      - id: only
        template: system/only.md
  - role: user
    sections:
      - id: invalid
        template: user/invalid.md
        provider: unknown
        when:
          field: retry.active
          equals: true
"""
    with patch.object(Path, "read_text", return_value=manifest):
        with pytest.raises(ValueError, match="registered provider"):
            load_manifest(Path("attack/manifest.yaml"), "attack")


def test_v2_manifests_declare_ordered_conditional_sections() -> None:
    root = (
        Path(__file__).parents[2]
        / "harness"
        / "agent_player_1"
        / "prompt_builder"
        / "input_sections"
    )
    common_ids = [
        "canonical_board_state",
        "scratch_board_state",
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
        assert set(manifest) == {"version", "phase", "messages"}
        assert [section["id"] for section in system_sections["sections"]] == [
            "tool_schemas",
            "phase_instructions",
        ]
        expected_ids = common_ids.copy()
        if phase == "synthesis":
            expected_ids.insert(1, "phase_reports")
        sections = user_sections["sections"]
        assert [section["id"] for section in sections] == expected_ids
        by_id = {section["id"]: section for section in sections}
        assert by_id["scratch_board_state"]["when"] == {
            "field": "scratch.status",
            "equals": "active",
        }
        assert by_id["forced_tool_retry"]["when"] == {
            "field": "retry.active",
            "equals": True,
        }
