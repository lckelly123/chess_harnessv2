"""Fixture generator, not a test. Run with the old shared/src on PYTHONPATH.

Prints JSON only; review and commit the output as fixtures/legacy_packets.json.
The ordinary test suite never imports or requires the legacy repository.
"""

import json

import chess
import chess.pgn
from chess_backend.playground.agent_player_1 import (
    AgentPlayer1Config,
    _instructions_for_tool_interface,
    build_force_tool_retry_input,
)
from chess_backend.playground.agent_player_1_phase_1 import (
    build_phase_1_defense_response_tools,
)
from chess_backend.playground.agent_player_1_phase_2 import (
    build_phase_2_attack_response_tools,
)
from chess_backend.playground.agent_player_1_phase_3 import (
    build_phase_3_decision_response_tools,
)
from chess_backend.playground.models import PlaygroundMoveRequest
from chess_backend.playground.phase_1_defense import (
    build_phase_1_defense_input_markdown,
    load_phase_1_defense_instructions,
)
from chess_backend.playground.phase_2_attack import (
    build_phase_2_attack_input_markdown,
    load_phase_2_attack_instructions,
)
from chess_backend.playground.phase_3_decision import (
    build_phase_3_decision_input_markdown,
    load_phase_3_decision_instructions,
)

DEFENSE = "Severity: None. No immediate defensive obligation was established by the reviewed position."
ATTACK = "Opportunity: Practical. The central pawn advance develops space without a verified forced gain."
BUILDERS = [
    build_phase_1_defense_input_markdown,
    build_phase_2_attack_input_markdown,
    build_phase_3_decision_input_markdown,
]
PHASES = ["defense", "attack", "synthesis"]


def capture():
    tools = [
        builder()
        for builder in (
            build_phase_1_defense_response_tools,
            build_phase_2_attack_response_tools,
            build_phase_3_decision_response_tools,
        )
    ]
    config = AgentPlayer1Config(tool_interface="text")
    static = [
        _instructions_for_tool_interface(loader(), config=config, tools=schemas)
        for loader, schemas in zip(
            (
                load_phase_1_defense_instructions,
                load_phase_2_attack_instructions,
                load_phase_3_decision_instructions,
            ),
            tools,
        )
    ]
    cases = []
    specifications = [
        ("initial", chess.STARTING_FEN, [], []),
        ("active", chess.STARTING_FEN, [], ["e4", "e5"]),
        (
            "middlegame",
            chess.STARTING_FEN,
            "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6".split(),
            [],
        ),
        ("en_passant", chess.STARTING_FEN, "e4 a6 e5 d5".split(), []),
        ("single_check", "4r1k1/8/8/8/8/8/8/4K3 w - - 0 1", [], []),
        ("double_check", "4r1k1/8/8/8/1b6/8/8/4K3 w - - 0 1", [], []),
        ("promotion", "4k3/1P6/8/8/8/8/8/4K3 w - - 0 1", [], []),
        ("black_to_move", chess.STARTING_FEN, ["e4"], []),
    ]
    for name, fen, moves, scratch_moves in specifications:
        board = chess.Board(fen)
        for move in moves:
            board.push_san(move)
        pgn = str(chess.pgn.Game.from_board(board))
        request = PlaygroundMoveRequest(
            game_id=name,
            fen=board.fen(),
            pgn=pgn,
            side="white" if board.turn else "black",
            legal_moves=(),
        )
        scratch = board.copy(stack=False)
        for move in scratch_moves:
            scratch.push_san(move)
        scratch_state = (
            {
                "status": "active",
                "fen": scratch.fen(),
                "moves_from_canonical": [{"san": move} for move in scratch_moves],
            }
            if scratch_moves
            else {"status": "unused"}
        )
        history = (
            [
                {
                    "type": "tool_call",
                    "tool": "inspect_square",
                    "justification": "Verify control of e4 before evaluating the central pawn advance.",
                    "arguments": {"board": "canonical", "square": "e4"},
                    "ok": True,
                    "result_summary": "Inspected canonical e4; occupant=empty; opponent attackers=0; agent pieces targeting=0.",
                }
            ]
            if name == "active"
            else []
        )
        correction = "Call exactly one available tool." if name == "active" else ""
        packets = []
        for phase, builder in zip(PHASES, BUILDERS):
            args = (request, DEFENSE, ATTACK) if phase == "synthesis" else (request,)
            packets.append(
                builder(
                    *args,
                    scratchboard_state=scratch_state,
                    tool_history_events=history,
                    protocol_correction=correction,
                )
            )
        cases.append(
            dict(
                name=name,
                fen=board.fen(),
                pgn=pgn,
                side=request.side,
                scratch_moves=scratch_moves,
                history=history,
                correction=correction,
                packets=dict(zip(PHASES, packets)),
            )
        )
    retries = {
        trigger: build_force_tool_retry_input(
            "# Position packet\n",
            previous_output="Check the central pawn advance.",
            trigger=trigger,
        )
        for trigger in ("reasoning_only_response", "reasoning_budget_exhausted")
    }
    return {
        "source": "legacy Agent Player 1 working tree, captured 2026-09-04",
        "tools": dict(zip(PHASES, tools)),
        "instructions": dict(zip(PHASES, static)),
        "defense_report": DEFENSE,
        "attack_report": ATTACK,
        "cases": cases,
        "retries": retries,
    }


if __name__ == "__main__":
    print(json.dumps(capture(), indent=2))
