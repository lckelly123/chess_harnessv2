"""Print fixtures from the old repo's actual builders; never used by normal tests.

Set PYTHONPATH to the old backend/shared/src, run this file, then review the JSON
as fixtures/legacy_baseline_packets.json. Only native Available Actions is omitted
because v2 embeds the text-tool contract in its stable developer instructions.
"""

import json
from types import SimpleNamespace

import chess
import chess.pgn
from chess_backend.harness import legal_move_identities
from chess_backend.playground.agent_input import build_agent_input_markdown_from_state
from chess_backend.playground.agent_player_2 import (
    AGENT_PLAYER_2_PROMPT_VERSION,
    build_agent_player_2_response_tools,
)


def capture():
    cases = []
    specs = [
        ("initial", chess.STARTING_FEN, []),
        ("black_to_move", chess.STARTING_FEN, ["e4"]),
        ("middlegame", chess.STARTING_FEN, "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6".split()),
        ("en_passant", chess.STARTING_FEN, "e4 a6 e5 d5".split()),
        ("single_check", "4r1k1/8/8/8/8/8/8/4K3 w - - 0 1", []),
        ("double_check", "4r1k1/8/8/8/1b6/8/8/4K3 w - - 0 1", []),
        ("promotion", "4k3/1P6/8/8/8/8/8/4K3 w - - 0 1", []),
        ("draw_status", "4k3/8/8/8/8/8/8/R3K3 w - - 100 51", []),
        ("rejected", chess.STARTING_FEN, []),
        ("correction", chess.STARTING_FEN, []),
    ]
    for name, fen, moves in specs:
        board = chess.Board(fen)
        for move in moves:
            board.push_san(move)
        pgn = str(chess.pgn.Game.from_board(board))
        side = "white" if board.turn else "black"
        history = (
            [
                {
                    "type": "tool_call",
                    "tool": "submit_move",
                    "ok": False,
                    "justification": "The attempted knight move needs correction to a canonical legal move.",
                    "arguments": {"move": "Nf5"},
                    "result_summary": "Rejected. `Nf5` is not legal on the current canonical board. Select a move from the canonical legal moves.",
                }
            ]
            if name == "rejected"
            else []
        )
        correction = (
            "Baseline must call only the `submit_move` tool."
            if name == "correction"
            else ""
        )
        packet = build_agent_input_markdown_from_state(
            game_id=name,
            agent_side=side,
            fen=board.fen(),
            pgn=pgn,
            legal_moves=legal_move_identities(board.fen()),
            # The formatter reads only .san; no artificial full MoveFrame needed.
            move_history=[SimpleNamespace(san=moves[-1])] if moves else [],
            tool_history_events=history,
            protocol_correction=correction,
            action_protocol_markdown="",
        )
        cases.append(
            dict(
                name=name,
                fen=board.fen(),
                pgn=pgn,
                side=side,
                history=history,
                correction=correction,
                packet=packet,
            )
        )
    return {
        "source": "Legacy Agent Player 2 working-tree builders, captured 2026-09-05; native action instructions excluded",
        "prompt_version": AGENT_PLAYER_2_PROMPT_VERSION,
        "tools": build_agent_player_2_response_tools(),
        "cases": cases,
    }


if __name__ == "__main__":
    print(json.dumps(capture(), indent=2))
