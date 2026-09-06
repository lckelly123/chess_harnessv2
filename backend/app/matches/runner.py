"""Authoritative, deterministic game loop around move-producing harnesses."""

from __future__ import annotations

import asyncio

import chess
import chess.pgn

from chess_core import normalize_move
from harness.contracts import PlayerHarness, TurnRequest

from .repository import MatchRepository


def _pgn(board: chess.Board) -> str:
    game = chess.pgn.Game.from_board(board)
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
    return game.accept(exporter)


class MatchRunner:
    def __init__(self, repository: MatchRepository):
        self._repository = repository

    async def run(
        self,
        match_id: str,
        *,
        white: PlayerHarness,
        black: PlayerHarness,
        white_name: str,
        black_name: str,
        cancelled: asyncio.Event,
    ) -> None:
        board = chess.Board()
        players = {"white": white, "black": black}
        names = {"white": white_name, "black": black_name}

        while True:
            if cancelled.is_set():
                self._repository.stop(match_id, "Stopped by the user.")
                return

            outcome = board.outcome(claim_draw=True)
            if outcome is not None:
                reason = outcome.termination.name.lower().replace("_", " ")
                self._repository.complete(match_id, outcome.result(), reason)
                return

            color = "white" if board.turn == chess.WHITE else "black"
            ply = len(board.move_stack)
            if not self._repository.set_turn(match_id, color, ply, names[color]):
                return

            request = TurnRequest(
                game_id=match_id,
                fen=board.fen(),
                pgn=_pgn(board),
                side=color,
                ply=ply,
            )
            decision = await players[color].choose_move(request)

            if cancelled.is_set():
                self._repository.stop(match_id, "Stopped by the user.")
                return

            normalized = normalize_move(board.fen(), decision.move.san)
            if normalized.uci != decision.move.uci:
                raise RuntimeError(
                    f"{names[color]} returned inconsistent SAN and UCI move data."
                )
            board.push(chess.Move.from_uci(normalized.uci))
            committed = self._repository.append_move_if_running(
                match_id,
                ply=len(board.move_stack),
                player=color,
                move=normalized,
                fen_after=board.fen(),
                decision=decision,
            )
            if not committed:
                return
