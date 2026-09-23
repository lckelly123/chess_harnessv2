"""Grade a completed turn against every legal move, outside the model context."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import chess
import chess.engine
import chess.pgn

POLICY_VERSION = "expected-points-v1"
# Native Stockfish WDL totals 1000. Half-draw credit gives 2000 score units.
POINT_UNITS = 2000
THRESHOLDS = ((400, "blunder"), (200, "mistake"), (100, "inaccuracy"), (40, "good"))


@dataclass(frozen=True)
class EvaluationSettings:
    executable: str = "stockfish"
    nodes_per_move: int = 500_000
    hash_mb: int = 128
    timeout_seconds: float = 180

    @classmethod
    def from_env(cls):
        return cls(
            executable=os.getenv("STOCKFISH_PATH", "stockfish"),
            nodes_per_move=int(os.getenv("POSITION_EVAL_NODES_PER_MOVE", "500000")),
            hash_mb=int(os.getenv("POSITION_EVAL_HASH_MB", "128")),
            timeout_seconds=float(os.getenv("POSITION_EVAL_TIMEOUT_SECONDS", "180")),
        )

    def __post_init__(self):
        if min(self.nodes_per_move, self.hash_mb, self.timeout_seconds) <= 0:
            raise ValueError("Position evaluation budgets must be positive.")


def classification(loss_units: int, *, is_best: bool) -> str:
    """Integer comparisons keep exact 2/5/10/20-point boundaries reliable."""
    if not 0 <= loss_units <= POINT_UNITS:
        raise ValueError("Expected-points loss must be between zero and one.")
    if is_best and loss_units == 0:
        return "best"
    return next(
        (name for cutoff, name in THRESHOLDS if loss_units >= cutoff), "excellent"
    )


class CompleteCandidates:
    """Never combine stale/bounded lines from different MultiPV depths."""

    def __init__(self, legal_moves):
        self.legal_moves = set(legal_moves)
        self.depths = {}

    def add(self, info):
        if (
            not info.get("pv")
            or not all(key in info for key in ("depth", "score", "wdl"))
            or info.get("lowerbound")
            or info.get("upperbound")
        ):
            return
        self.depths.setdefault(info["depth"], {})[info.get("multipv", 1)] = dict(info)

    def finish(self):
        for depth in sorted(self.depths, reverse=True):
            lines = self.depths[depth]
            if set(lines) != set(range(1, len(self.legal_moves) + 1)):
                continue
            ordered = [lines[index] for index in sorted(lines)]
            if {line["pv"][0] for line in ordered} == self.legal_moves:
                return ordered
        raise ValueError(
            "Stockfish did not return a complete depth for every legal move."
        )


def grade_candidates(board: chess.Board, chosen_uci: str, lines: list[dict]) -> dict:
    """Rank by expected points; retain only strictly better training targets."""
    legal_moves = set(board.legal_moves)
    if (
        len(lines) != len(legal_moves)
        or {line["pv"][0] for line in lines} != legal_moves
        or len({line["depth"] for line in lines}) != 1
    ):
        raise ValueError(
            "Evaluation must cover every legal move at one complete depth."
        )
    candidates = []
    for info in lines:
        score = info["score"].pov(board.turn)
        wdl = info["wdl"].pov(board.turn)
        if wdl.total() != 1000 or min(wdl) < 0:
            raise ValueError("Expected native Stockfish WDL on a 1000-point scale.")
        points = 2 * wdl.wins + wdl.draws
        move = info["pv"][0]
        cursor = board.copy()
        for pv_move in info["pv"]:
            if pv_move not in cursor.legal_moves:
                raise ValueError("Stockfish returned an illegal principal variation.")
            cursor.push(pv_move)
        candidates.append(
            (
                points,
                score,
                {
                    "move_uci": move.uci(),
                    "move_san": board.san(move),
                    "score_cp": score.score(),
                    "mate": score.mate(),
                    "wdl": {"wins": wdl.wins, "draws": wdl.draws, "losses": wdl.losses},
                    "expected_points": points / POINT_UNITS,
                    "pv_uci": [m.uci() for m in info["pv"]],
                    "depth": info["depth"],
                },
            )
        )
    # CP/mate score only breaks WDL ties. UCI order makes exact ties repeatable.
    candidates.sort(key=lambda c: (-c[0], -c[1], c[2]["move_uci"]))
    best_points, best_score, best = candidates[0]
    chosen = next((c for c in candidates if c[2]["move_uci"] == chosen_uci), None)
    if chosen is None:
        raise ValueError("The submitted move is not legal in the saved position.")
    chosen_points, chosen_score, chosen_payload = chosen
    for rank, (points, _, payload) in enumerate(candidates, 1):
        payload.update(
            rank=rank,
            expected_points_loss=(best_points - points) / POINT_UNITS,
        )
    better = [
        {**payload, "improvement_over_chosen": (points - chosen_points) / POINT_UNITS}
        for points, _, payload in candidates
        if points > chosen_points
    ]
    return {
        "classification": classification(
            best_points - chosen_points, is_best=chosen_score == best_score
        ),
        "expected_points_loss": (best_points - chosen_points) / POINT_UNITS,
        # Mate remains a separate score, never an arbitrary large CP value.
        "cp_loss": (
            best_score.score() - chosen_score.score()
            if not best_score.is_mate() and not chosen_score.is_mate()
            else None
        ),
        "better_moves": better,
        "best": best,
        "chosen": chosen_payload,
    }


@lru_cache(maxsize=8)
def _binary_digest(path: str, modified_ns: int) -> str:
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class StockfishEvaluator:
    def __init__(self, settings: EvaluationSettings | None = None):
        self.settings = settings or EvaluationSettings.from_env()
        self._slot = asyncio.Semaphore(1)

    async def evaluate(self, *, fen: str, pgn: str, move_uci: str) -> dict:
        game = chess.pgn.read_game(io.StringIO(pgn))
        if game is None or game.errors:
            raise ValueError("Cannot evaluate an invalid PGN history.")
        board = game.end().board()
        if board.fen() != chess.Board(fen).fen():
            raise ValueError("Evaluation PGN does not recreate the saved FEN.")
        if chess.Move.from_uci(move_uci) not in board.legal_moves:
            raise ValueError("The submitted move is not legal in the saved position.")
        async with self._slot:
            return await self._analyse(board, move_uci)

    async def _analyse(self, board, move_uci):
        settings = self.settings
        executable = shutil.which(settings.executable)
        if executable is None:
            raise FileNotFoundError("Stockfish is unavailable; check STOCKFISH_PATH.")
        digest = await asyncio.to_thread(
            _binary_digest, executable, Path(executable).stat().st_mtime_ns
        )
        collector = CompleteCandidates(board.legal_moves)
        node_limit = settings.nodes_per_move * len(collector.legal_moves)
        transport = engine = None
        started = datetime.now(UTC)
        try:
            async with asyncio.timeout(settings.timeout_seconds):
                transport, engine = await chess.engine.popen_uci(executable)
                await engine.configure(
                    {"Threads": 1, "Hash": settings.hash_mb, "UCI_ShowWDL": True}
                )
                with await engine.analysis(
                    board,
                    chess.engine.Limit(nodes=node_limit),
                    multipv=len(collector.legal_moves),
                    game=object(),
                ) as stream:
                    async for info in stream:
                        collector.add(info)
                lines = collector.finish()
                result = grade_candidates(board, move_uci, lines)
                result["evaluation"] = {
                    "status": "completed",
                    "policy_version": POLICY_VERSION,
                    "engine_name": engine.id.get("name", "Stockfish"),
                    "engine_sha256": digest,
                    "wdl_model": "native_stockfish",
                    "perspective": "side_to_move",
                    "side": "white" if board.turn else "black",
                    "root_fen": board.fen(),
                    "thresholds": {
                        name: units / POINT_UNITS for units, name in THRESHOLDS
                    },
                    "nodes_per_move": settings.nodes_per_move,
                    "node_limit": node_limit,
                    "nodes": max(line.get("nodes", 0) for line in lines),
                    "depth": lines[0]["depth"],
                    "threads": 1,
                    "hash_mb": settings.hash_mb,
                    "legal_move_count": len(collector.legal_moves),
                    "evaluated_move_count": len(lines),
                    "best": result.pop("best"),
                    "chosen": result.pop("chosen"),
                    "started_at": started.isoformat(),
                    "finished_at": datetime.now(UTC).isoformat(),
                }
                return result
        except TimeoutError as exc:
            raise TimeoutError(
                f"Stockfish evaluation exceeded {settings.timeout_seconds:g} seconds."
            ) from exc
        finally:
            try:
                if engine is not None:
                    await asyncio.wait_for(engine.quit(), timeout=5)
            except Exception:
                pass
            finally:
                if transport is not None:
                    transport.close()
