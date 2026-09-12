"""Read saved PGNs and expose their final positions as immutable records."""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import chess
import chess.pgn

from .models import SavedPosition, SavedPositionSnapshot

POSITION_DIRECTORY = Path(__file__).resolve().parent / "positions"


class InvalidSavedPositionError(ValueError):
    """A saved PGN could not be represented as a selectable position."""


@dataclass(frozen=True, slots=True)
class SavedPositionDocument:
    """A saved position plus the source PGN used for one-turn harness input."""

    position: SavedPosition
    pgn: str


def _header_value(game: chess.pgn.Game, name: str) -> str | None:
    value = game.headers.get(name, "").strip()
    return value if value and value != "?" else None


def _position_paths(position_directory: Path) -> list[Path]:
    if not position_directory.exists():
        return []
    return sorted(
        position_directory.rglob("*.pgn"),
        key=lambda path: path.relative_to(position_directory).as_posix().casefold(),
    )


def _read_position(path: Path, root: Path) -> SavedPositionDocument:
    try:
        pgn = path.read_text(encoding="utf-8-sig")
        game = chess.pgn.read_game(StringIO(pgn))
    except (OSError, UnicodeError, ValueError) as exc:
        raise InvalidSavedPositionError(
            f"Could not read saved position {path.name}: {exc}"
        ) from exc

    if game is None:
        raise InvalidSavedPositionError(f"Saved position {path.name} is empty.")
    if game.errors:
        raise InvalidSavedPositionError(
            f"Saved position {path.name} contains invalid PGN: {game.errors[0]}"
        )

    board = game.board()
    last_san = "Initial position"
    last_player: str | None = None
    from_square: str | None = None
    to_square: str | None = None

    for move in game.mainline_moves():
        last_san = board.san(move)
        last_player = "white" if board.turn == chess.WHITE else "black"
        from_square = chess.square_name(move.from_square)
        to_square = chess.square_name(move.to_square)
        board.push(move)

    relative_path = path.relative_to(root)
    event = _header_value(game, "Event")
    return SavedPositionDocument(
        position=SavedPosition(
            id=relative_path.with_suffix("").as_posix(),
            name=event or path.stem.replace("_", " ").title(),
            source_file=relative_path.as_posix(),
            white=_header_value(game, "White"),
            black=_header_value(game, "Black"),
            side_to_move="white" if board.turn == chess.WHITE else "black",
            move_count=board.ply(),
            position=SavedPositionSnapshot(
                ply=board.ply(),
                fen=board.fen(),
                san=last_san,
                player=last_player,
                from_square=from_square,
                to_square=to_square,
            ),
        ),
        pgn=pgn,
    )


def list_saved_positions(
    position_directory: Path = POSITION_DIRECTORY,
) -> list[SavedPosition]:
    """Return each PGN under the saved-position directory in stable order."""

    return [
        _read_position(path, position_directory).position
        for path in _position_paths(position_directory)
    ]


def get_saved_position(
    position_id: str,
    position_directory: Path = POSITION_DIRECTORY,
) -> SavedPositionDocument | None:
    """Return one catalogued position by stable ID, including its source PGN."""

    for path in _position_paths(position_directory):
        relative_path = path.relative_to(position_directory)
        if relative_path.with_suffix("").as_posix() == position_id:
            return _read_position(path, position_directory)
    return None
