from copy import deepcopy

import pytest
from conftest import JUSTIFICATION

from chess_core import (
    STARTING_FEN,
    IllegalMoveError,
    apply_move,
    scan_opponent_forcing_moves,
)
from harness.agent_player_1.nodes import parse_tool_call
from harness.agent_player_1.tools import (
    ToolProtocolError,
    ToolRejected,
    execute_tool,
    tool_schemas,
)


def execute(
    name, arguments, moves=None, phase="defense", side="white", fen=STARTING_FEN
):
    return execute_tool(
        phase=phase,
        name=name,
        arguments=arguments,
        canonical_fen=fen,
        side=side,
        scratch_moves=moves or [],
    )


@pytest.mark.parametrize("move", ["e5", "e2e4", "--", "0000"])
def test_only_exact_legal_san_is_accepted(move):
    with pytest.raises(ToolRejected):
        execute("scratch_play_move", {"move": move, "justification": JUSTIFICATION})


@pytest.mark.parametrize(
    "field", ["fen", "position_id", "positions", "tool", "arguments", "action", "board"]
)
def test_rejects_injected_board_or_envelope_fields(field):
    with pytest.raises(ToolProtocolError):
        execute(
            "scratch_play_move",
            {"move": "e4", "justification": JUSTIFICATION, field: "injected"},
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {"move": "e4"},
        {"move": "e4", "justification": "check"},
        {"move": 42, "justification": JUSTIFICATION},
    ],
)
def test_missing_generic_and_nonstring_arguments(arguments):
    with pytest.raises(ToolProtocolError):
        execute("scratch_play_move", arguments)


def test_scratch_undo_reset_do_not_mutate_input():
    moves = ["e4", "e5"]
    previous = deepcopy(moves)
    assert execute("scratch_undo", {"justification": JUSTIFICATION}, moves)[
        "scratch_moves"
    ] == ["e4"]
    assert (
        execute("scratch_reset", {"justification": JUSTIFICATION}, moves)[
            "scratch_moves"
        ]
        == []
    )
    assert moves == previous
    assert execute("scratch_undo", {"justification": JUSTIFICATION})["result"][
        "scratchboard"
    ] == {"status": "unused"}


def test_inspection_is_relative_to_agent_not_scratch_side_to_move():
    result = execute(
        "inspect_square",
        {"board": "scratch", "square": "e4", "justification": JUSTIFICATION},
        ["e4"],
    )["result"]
    assert result["side_to_move"] == "black"
    assert result["agent_side"] == "white"
    assert result["piece"] == {"square": "e4", "color": "white", "piece": "pawn"}
    assert (
        execute(
            "inspect_square",
            {"board": "canonical", "square": "e4", "justification": JUSTIFICATION},
            ["e4"],
        )["result"]["piece"]
        is None
    )


@pytest.mark.parametrize("board,square", [("other", "e4"), ("scratch", "i9")])
def test_invalid_inspection_is_recoverable(board, square):
    with pytest.raises(ToolRejected):
        execute(
            "inspect_square",
            {"board": board, "square": square, "justification": JUSTIFICATION},
        )


def test_other_phase_terminal_tool_is_not_available():
    with pytest.raises(ToolProtocolError):
        execute("submit_move", {"move": "e4", "justification": JUSTIFICATION})


def test_move_schemas_are_stable_strings_not_enums():
    for phase in ("defense", "attack", "synthesis"):
        schemas = tool_schemas(phase)
        assert len(schemas) == 5
        for tool in schemas:
            assert tool["strict"]
            assert tool["parameters"]["additionalProperties"] is False
            if "move" in tool["parameters"]["properties"]:
                assert "enum" not in tool["parameters"]["properties"]["move"]


def test_omitted_promotion_piece_is_accepted_as_a_queen():
    result = execute(
        "submit_move",
        {"move": "a8", "justification": JUSTIFICATION},
        phase="synthesis",
        fen="7k/P7/8/8/8/8/8/7K w - - 0 1",
    )

    assert result["decision"]["move"] == "a8"


@pytest.mark.parametrize(
    "text",
    [
        "{}",
        "<agent_tool_call>{}</agent_tool_call>",
        '<agent_tool_call>{"tool":"scratch_reset","arguments":{}}</agent_tool_call>extra',
        "<agent_tool_call>{}</agent_tool_call><agent_tool_call>{}</agent_tool_call>",
        "<agent_tool_call>[1]</agent_tool_call>",
        "<agent_tool_call>{bad}</agent_tool_call>",
        "</agent_tool_call><agent_tool_call>{}",
    ],
)
def test_malformed_tagged_output(text):
    with pytest.raises(ToolProtocolError):
        parse_tool_call(text)


def test_visible_prefix_is_allowed_but_never_executed():
    call = parse_tool_call(
        'Unverified analysis. <agent_tool_call>{"tool":"scratch_reset","arguments":{}}</agent_tool_call>'
    )
    assert call["tool"] == "scratch_reset"


def test_checkers_and_evasions_restored_without_a_hypothetical_pass():
    scan = scan_opponent_forcing_moves("4r1k1/8/8/8/1b6/8/8/4K3 w - - 0 1")
    assert scan.status == "in_check"
    assert scan.current_check.check_type == "double_check"
    assert {piece.square for piece in scan.current_check.checking_pieces} == {
        "e8",
        "b4",
    }
    assert scan.current_check.legal_evasions
    assert all(e.evasion_type == "king_move" for e in scan.current_check.legal_evasions)
    assert not scan.checks and not scan.captures


@pytest.mark.parametrize("move", ["--", "Z0", "0000", "@@@@"])
def test_core_does_not_accept_null_san(move):
    with pytest.raises(IllegalMoveError):
        apply_move(STARTING_FEN, move)
