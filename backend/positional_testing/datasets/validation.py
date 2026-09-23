"""Validate source history and frozen-set invariants before any database write."""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
from collections import Counter
from pathlib import Path

import chess
import chess.pgn

QUOTAS = {
    ("opening", "quiet"): 32,
    ("opening", "tactical"): 8,
    ("middlegame", "quiet"): 96,
    ("middlegame", "tactical"): 24,
    ("endgame", "quiet"): 32,
    ("endgame", "tactical"): 8,
}
PHASE_RULE = "material-development-v1"


def position_key(board: chess.Board) -> str:
    """Group transpositions, retaining turn, castling and legal en passant rights."""
    identity = " ".join(board.fen(en_passant="legal").split()[:4])
    return hashlib.sha256(identity.encode()).hexdigest()


def phase_of(board: chess.Board) -> str | None:
    """Conservative reproducible phase buckets; ambiguous boundaries are excluded."""
    weights = {chess.KNIGHT: 1, chess.BISHOP: 1, chess.ROOK: 2, chess.QUEEN: 4}
    material_phase = sum(
        len(board.pieces(piece, color)) * weight
        for piece, weight in weights.items()
        for color in chess.COLORS
    )
    if material_phase <= 8:
        return "endgame"
    if board.fullmove_number <= 12 and material_phase >= 18:
        return "opening"
    if board.fullmove_number >= 13 and material_phase >= 10:
        return "middlegame"
    return None


def clean_prefix(board: chess.Board) -> str:
    """Export only legal past moves; no results, player hints, evals or variations."""
    game = chess.pgn.Game.from_board(board)
    game.headers.clear()
    if board.root().fen() != chess.STARTING_FEN:
        game.headers["SetUp"] = "1"
        game.headers["FEN"] = board.root().fen()
    game.headers["Result"] = "*"
    return game.accept(
        chess.pgn.StringExporter(headers=True, variations=False, comments=False)
    )


def validate_position(row: dict) -> chess.Board:
    uuid.UUID(row["id"])
    if row["split"] not in {"train", "test"}:
        raise ValueError("Unknown dataset split")
    if (row["phase"], row["position_type"]) not in QUOTAS:
        raise ValueError("Unknown phase/type")
    if row["source"] not in {"lichess_game", "lichess_puzzle"}:
        raise ValueError("Unknown source")
    if not re.fullmatch(r"[A-Za-z0-9]{8}", row["source_game_id"]):
        raise ValueError("Invalid source game ID")
    stream = io.StringIO(row["pgn_prefix"])
    game = chess.pgn.read_game(stream)
    if game is None or game.errors or chess.pgn.read_game(stream) is not None:
        raise ValueError("Invalid or multiple prefix PGNs")
    if game.comment:
        raise ValueError("Prefix includes root annotations")
    if not isinstance(row["metadata"], dict):
        raise ValueError("Position metadata must be an object")
    if game.headers.get("Result") != "*":
        raise ValueError("Prefix leaks the source game's result")
    if set(game.headers) - {
        "Event",
        "Site",
        "Date",
        "Round",
        "White",
        "Black",
        "Result",
        "SetUp",
        "FEN",
    }:
        raise ValueError("Unexpected prefix headers")
    for name in ("Event", "Site", "Date", "Round", "White", "Black"):
        if game.headers.get(name, "?") not in {"?", "????.??.??"}:
            raise ValueError("Prefix includes source-game hints")
    board = game.board()
    last_san = last_uci = None
    for node in game.mainline():
        if node.comment or node.starting_comment or node.nags:
            raise ValueError("Prefix includes annotations")
        if len(node.parent.variations) != 1:
            raise ValueError("Prefix includes alternative lines")
        if node.move not in board.legal_moves:
            raise ValueError("Illegal source move")
        last_san, last_uci = board.san(node.move), node.move.uci()
        board.push(node.move)
    if not board.is_valid() or board.is_game_over(claim_draw=True):
        raise ValueError("Position is invalid or already terminal/draw-claimable")
    if len(row["fen"].split()) != 6 or row["fen"] != board.fen():
        raise ValueError("FEN does not match replayed PGN")
    if last_uci != row["last_move_uci"] or last_san != row["last_move_san"]:
        raise ValueError("Last move does not match history")
    if board.ply() != row["source_ply"]:
        raise ValueError("Source ply does not match history")
    if row["position_key"] != position_key(board):
        raise ValueError("Incorrect position key")
    if phase_of(board) != row["phase"]:
        raise ValueError("Incorrect phase classification")
    if row["position_type"] == "quiet" and board.is_check():
        raise ValueError("Quiet collection contains a check evasion")
    return board


def validate_collection(rows: list[dict], version: str) -> dict:
    counts, colors = Counter(), Counter()
    ids, games, keys = set(), set(), set()
    for row in rows:
        if row["dataset_version"] != version:
            raise ValueError("Dataset version mismatch")
        board = validate_position(row)
        for seen, value, label in (
            (ids, row["id"], "ID"),
            (games, row["source_game_id"], "source game"),
            (keys, row["position_key"], "board position"),
        ):
            if value in seen:
                raise ValueError(f"Duplicate {label}: {value}")
            seen.add(value)
        bucket = (row["split"], row["phase"], row["position_type"])
        counts[bucket] += 1
        colors[(*bucket, "white" if board.turn else "black")] += 1
    expected = {
        (split, *bucket): size
        for split in ("train", "test")
        for bucket, size in QUOTAS.items()
    }
    if dict(counts) != expected:
        raise ValueError(f"Collection quotas do not match: {dict(counts)}")
    for bucket, size in expected.items():
        for color in ("white", "black"):
            if colors[(*bucket, color)] != size // 2:
                raise ValueError(f"Unbalanced side to move: {bucket}")
    return {
        "positions": len(rows),
        "unique_games": len(games),
        "unique_boards": len(keys),
        "counts": [
            {"split": s, "phase": p, "position_type": t, "count": n}
            for (s, p, t), n in sorted(counts.items())
        ],
        "validation": "all PGNs replay to FEN, last move, ply, phase and key; no duplicates; exact quotas and colors",
    }


def load_collection(directory: Path) -> tuple[list[dict], dict, dict]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    payload = (directory / "positions.jsonl").read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest["positions_sha256"]:
        raise ValueError("Position file checksum mismatch")
    rows = [json.loads(line) for line in payload.decode().splitlines() if line.strip()]
    report = validate_collection(rows, manifest["version"])
    if report["positions"] != manifest["position_count"]:
        raise ValueError("Manifest position count mismatch")
    report["reference_evaluations"] = len(load_evaluations(directory, manifest, rows))
    return rows, manifest, report


def load_evaluations(directory: Path, manifest: dict, rows: list[dict]) -> list[dict]:
    payload = (directory / "evaluations.jsonl").read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest["evaluations_sha256"]:
        raise ValueError("Evaluation file checksum mismatch")
    evaluations = [json.loads(line) for line in payload.decode().splitlines() if line]
    by_id = {row["id"]: row for row in rows}
    if len(evaluations) != len(rows) or {e["position_id"] for e in evaluations} != set(
        by_id
    ):
        raise ValueError("Expected one curation evaluation per position")
    for evaluation in evaluations:
        board = chess.Board(by_id[evaluation["position_id"]]["fen"])
        if evaluation["perspective"] != "side_to_move":
            raise ValueError("Unsupported evaluation perspective")
        if (evaluation["best_score_cp"] is None) == (evaluation["best_mate"] is None):
            raise ValueError("Expected exactly one centipawn or mate score")
        if not evaluation["engine_name"] or evaluation["node_limit"] <= 0:
            raise ValueError("Incomplete engine provenance")
        payload = evaluation["payload"]
        if (
            payload["engine"] != evaluation["engine_name"]
            or payload["node_limit"] != evaluation["node_limit"]
            or payload["perspective"] != evaluation["perspective"]
        ):
            raise ValueError("Reference engine provenance disagrees with its payload")
        variations = payload["pvs"]
        if not variations or evaluation["best_move_uci"] != variations[0]["move_uci"]:
            raise ValueError("Best move does not match reference variations")
        if (evaluation["best_score_cp"], evaluation["best_mate"]) != (
            variations[0]["score_cp"],
            variations[0]["mate"],
        ):
            raise ValueError("Best score does not match reference variations")
        if len({variation["move_uci"] for variation in variations}) != len(variations):
            raise ValueError("Duplicate reference candidate moves")
        for variation in variations:
            cursor = board.copy()
            if (variation["score_cp"] is None) == (variation["mate"] is None):
                raise ValueError("Invalid reference candidate score")
            if (
                not variation["moves_uci"]
                or variation["move_uci"] != variation["moves_uci"][0]
            ):
                raise ValueError("Invalid reference root move")
            for index, uci in enumerate(variation["moves_uci"]):
                move = chess.Move.from_uci(uci)
                if move not in cursor.legal_moves:
                    raise ValueError("Reference variation contains an illegal move")
                sans = variation["moves_san"]
                if (
                    len(sans) != len(variation["moves_uci"])
                    or cursor.san(move) != sans[index]
                ):
                    raise ValueError("Reference SAN does not match its moves")
                cursor.push(move)
    return evaluations
