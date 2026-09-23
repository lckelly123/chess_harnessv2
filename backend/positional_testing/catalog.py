"""Read the PostgreSQL library; expose exercise metadata without engine answers."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import chess
import psycopg

from .datasets import store
from .datasets.validation import validate_position
from .models import SavedPosition, SavedPositionSnapshot


class InvalidSavedPositionError(ValueError):
    """A stored position failed validation before being sent to a harness."""


class PositionLibraryUnavailableError(RuntimeError):
    """The PostgreSQL position library could not be read."""


@dataclass(frozen=True, slots=True)
class SavedPositionDocument:
    position: SavedPosition
    pgn: str


def _summary(row: dict) -> SavedPosition:
    board = chess.Board(row["fen"])
    last = chess.Move.from_uci(row["last_move_uci"])
    metadata = row["metadata"]
    return SavedPosition(
        id=str(row["id"]),
        name=f"{row['phase'].capitalize()} · move {board.fullmove_number}",
        dataset_version=row["dataset_version"],
        split=row["split"],
        phase=row["phase"],
        position_type=row["position_type"],
        source=row["source"],
        source_game_id=row["source_game_id"],
        source_url=row["source_url"],
        opening=metadata.get("opening"),
        themes=metadata.get("themes", []),
        puzzle_rating=metadata.get("puzzle_rating"),
        side_to_move="white" if board.turn else "black",
        move_count=row["source_ply"],
        position=SavedPositionSnapshot(
            ply=row["source_ply"],
            fen=row["fen"],
            san=row["last_move_san"],
            player="black" if board.turn else "white",
            from_square=chess.square_name(last.from_square),
            to_square=chess.square_name(last.to_square),
        ),
    )


def list_saved_positions() -> list[SavedPosition]:
    try:
        return [_summary(row) for row in store.list_position_rows()]
    except psycopg.Error as exc:
        raise PositionLibraryUnavailableError(
            "The position library is unavailable. Check the database service and retry."
        ) from exc


def get_saved_position(position_id: str) -> SavedPositionDocument | None:
    try:
        identifier = str(UUID(position_id))
    except ValueError:
        return None
    try:
        row = store.get_position_row(identifier)
    except psycopg.Error as exc:
        raise PositionLibraryUnavailableError(
            "The position library is unavailable. Check the database service and retry."
        ) from exc
    if row is None:
        return None
    row["id"] = str(row["id"])
    try:
        validate_position(row)
    except (ValueError, KeyError) as exc:
        raise InvalidSavedPositionError(
            "This position's stored history is inconsistent. Revalidate the dataset before running it."
        ) from exc
    return SavedPositionDocument(position=_summary(row), pgn=row["pgn_prefix"])
