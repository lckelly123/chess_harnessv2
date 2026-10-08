from copy import deepcopy
from importlib import import_module
from types import SimpleNamespace

import chess
import pytest

from harness.contracts import TurnRequest

EXAMPLE_FEN = "r1b1r1k1/pp3ppp/5q2/3p4/1P1P1B2/P2Q3P/5PP1/2R2RK1 w - - 0 1"


@pytest.fixture(params=["agent_player_2", "agent_player3"])
def agent(request):
    root = f"harness.{request.param}"
    return SimpleNamespace(
        initial_state=import_module(f"{root}.state").initial_state,
        build_prompt=import_module(f"{root}.prompt_builder").build_prompt,
        board_context=import_module(
            f"{root}.prompt_builder.context"
        ).build_board_state_context,
        execute_tool=import_module(f"{root}.tools").execute_tool,
    )


def make_state(agent, fen):
    side = "white" if chess.Board(fen).turn else "black"
    return agent.initial_state(
        TurnRequest(game_id="hypothetical-moves", fen=fen, pgn="*", side=side)
    )


def play(agent, state, move):
    result = agent.execute_tool(
        phase="synthesis",
        name="scratch_play_move",
        arguments={"move": move},
        canonical_fen=state["canonical_fen"],
        side=state["side"],
        scratch_moves=state["scratch_moves"],
        tested_lines=state["tested_lines"],
        active_branch_id=state["active_branch_id"],
    )
    for key in ("scratch_moves", "tested_lines", "active_branch_id"):
        state[key] = result[key]


def board_context(agent, state, source="canonical"):
    return agent.board_context(
        state, source=source, include_scratch_moves=source == "scratch"
    )


def piece_moves(groups):
    return {
        piece.square: piece.legal_moves for group in groups for piece in group.pieces
    }


def all_moves(groups):
    return [move for moves in piece_moves(groups).values() for move in moves]


@pytest.mark.parametrize("turn", [chess.WHITE, chess.BLACK])
def test_canonical_lists_both_sides_without_mutating_state(agent, turn):
    board = chess.Board(EXAMPLE_FEN)
    board.turn = turn
    state = make_state(agent, board.fen())
    before = deepcopy(state)
    context = board_context(agent, state)
    packet = agent.build_prompt(state)

    assert sorted(all_moves(context.side_to_move_piece_groups)) == sorted(
        board.san(move) for move in board.legal_moves
    )
    hypothetical = board.copy()
    hypothetical.turn = not turn
    hypothetical.ep_square = None
    assert sorted(all_moves(context.hypothetical_piece_groups)) == sorted(
        hypothetical.san(move) for move in hypothetical.legal_moves
    )
    assert context.hypothetical_side_to_move != context.side_to_move
    assert context.hypothetical_unavailable_reason is None
    assert (
        f"## Legal Moves for {context.hypothetical_side_to_move} if their turn"
        in packet.dynamic_input
    )
    assert (
        "The actual side to move is still " + context.side_to_move
        in packet.dynamic_input
    )
    assert "for the actual side to move on that board" in packet.instructions
    assert state == before
    if turn == chess.WHITE:
        moves = piece_moves(context.hypothetical_piece_groups)
        assert moves["f6"][:2] == ("Qxf4", "Qxd4")
        assert moves["c8"][0] == "Bxh3"
        assert moves["f7"] == ()
        assert "Pawn f7: none" in packet.dynamic_input


@pytest.mark.parametrize(
    ("turn", "line"),
    [
        (chess.WHITE, ["e4"]),
        (chess.WHITE, ["e4", "e5"]),
        (chess.BLACK, ["e5"]),
        (chess.BLACK, ["e5", "e4"]),
    ],
)
def test_scratch_lists_follow_its_current_turn_and_position(agent, turn, line):
    board = chess.Board()
    board.turn = turn
    state = make_state(agent, board.fen())
    for move in line:
        play(agent, state, move)
        board.push_san(move)
    before = deepcopy(state)
    context = board_context(agent, state, "scratch")
    packet = agent.build_prompt(state)
    canonical, scratch = packet.dynamic_input.split("# Scratch Position", 1)
    scratch = scratch.split("# Running Thoughts", 1)[0]
    actual_side = "White" if board.turn else "Black"
    other_side = "Black" if board.turn else "White"

    assert f"## Legal Moves for {actual_side}\n" in scratch
    assert f"## Legal Moves for {other_side} if their turn" in scratch
    assert f"The actual side to move is still {actual_side}." in scratch
    assert " if their turn" in canonical
    assert sorted(all_moves(context.side_to_move_piece_groups)) == sorted(
        board.san(move) for move in board.legal_moves
    )
    board.turn = not board.turn
    board.ep_square = None
    assert sorted(all_moves(context.hypothetical_piece_groups)) == sorted(
        board.san(move) for move in board.legal_moves
    )
    assert state == before


@pytest.mark.parametrize("source", ["canonical", "scratch"])
def test_hypothetical_turn_expires_en_passant_only_on_the_copy(agent, source):
    if source == "canonical":
        state = make_state(
            agent, "rnbqkbnr/1pp1pppp/p7/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3"
        )
    else:
        state = make_state(
            agent, "rnbqkbnr/1ppppppp/p7/4P3/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2"
        )
        play(agent, state, "d5")
    before = deepcopy(state)
    context = board_context(agent, state, source)

    assert context.en_passant == "d6"
    assert "exd6" in all_moves(context.side_to_move_piece_groups)
    assert context.hypothetical_unavailable_reason is None
    assert piece_moves(context.hypothetical_piece_groups)["d5"] == ("d4",)
    assert (
        "En passant: none after the hypothetical skipped turn."
        in agent.build_prompt(state).dynamic_input
    )
    assert state == before


@pytest.mark.parametrize(
    ("fen", "square", "expected"),
    [
        ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e8", {"O-O", "O-O-O"}),
        ("4k3/4n3/8/8/8/8/8/K3R3 w - - 0 1", "e7", set()),
        ("7k/8/8/8/8/8/p7/7K w - - 0 1", "a2", {"a1=Q+", "a1=R+", "a1=B", "a1=N"}),
    ],
    ids=["castling", "pinned-knight", "promotion"],
)
def test_hypothetical_moves_obey_special_move_and_king_safety_rules(
    agent, fen, square, expected
):
    moves = piece_moves(
        board_context(agent, make_state(agent, fen)).hypothetical_piece_groups
    )
    if square == "e8":
        assert expected <= set(moves[square])
    else:
        assert set(moves[square]) == expected
    if square == "a2":
        assert moves[square] == ("a1=Q+", "a1=R+", "a1=B", "a1=N")


def test_hypothetical_mates_sort_before_checking_captures(agent):
    state = make_state(agent, "k7/8/8/8/5q2/8/6PP/7K w - - 0 1")
    moves = piece_moves(board_context(agent, state).hypothetical_piece_groups)["f4"]
    assert moves.index("Qf1#") < moves.index("Qxh2+")


@pytest.mark.parametrize("source", ["canonical", "scratch"])
def test_checked_side_cannot_be_skipped(agent, source):
    if source == "canonical":
        state = make_state(agent, "4k3/8/8/8/8/8/4r3/4K3 w - - 0 1")
    else:
        state = make_state(agent, EXAMPLE_FEN)
        play(agent, state, "Qxh7+")
    context = board_context(agent, state, source)
    packet = agent.build_prompt(state)

    assert context.check_status == "Yes"
    assert context.hypothetical_piece_groups == ()
    assert context.hypothetical_unavailable_reason == (
        f"Unavailable: {context.side_to_move} is in check and cannot skip the turn."
    )
    assert context.hypothetical_unavailable_reason in packet.dynamic_input
    assert all_moves(context.side_to_move_piece_groups)


@pytest.mark.parametrize("ending", ["checkmate", "stalemate"])
def test_terminal_scratch_positions_do_not_generate_hypothetical_moves(agent, ending):
    if ending == "checkmate":
        board = chess.Board()
        for move in ("f3", "e5", "g4"):
            board.push_san(move)
        state = make_state(agent, board.fen())
        play(agent, state, "Qh4#")
    else:
        state = make_state(agent, "7k/8/5K2/5Q2/8/8/8/8 w - - 0 1")
        play(agent, state, "Qg6")
    context = board_context(agent, state, "scratch")
    assert all_moves(context.side_to_move_piece_groups) == []
    assert context.hypothetical_piece_groups == ()
    assert context.hypothetical_unavailable_reason is not None
    assert (
        context.hypothetical_unavailable_reason
        in agent.build_prompt(state).dynamic_input
    )


def test_drawn_position_reports_unavailable_hypothetical_moves(agent):
    state = make_state(agent, "7k/8/8/8/8/8/8/K7 w - - 0 1")
    context = board_context(agent, state)
    assert context.hypothetical_piece_groups == ()
    assert (
        context.hypothetical_unavailable_reason
        == "Unavailable: this position is game over."
    )
