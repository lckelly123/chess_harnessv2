"""Public deterministic chess API used by matches and agent harnesses."""

from .analysis import (
    inspect_square,
    scan_agent_forcing_moves,
    scan_opponent_forcing_moves,
    static_exchange,
)
from .errors import (
    ChessCoreError,
    IllegalMoveError,
    InvalidPositionError,
    InvalidSquareError,
)
from .models import (
    CheckEvasion,
    ColorName,
    CurrentCheck,
    ForcingMove,
    ForcingMoveScan,
    MoveIdentity,
    MoveTransition,
    PieceInfo,
    PositionStatus,
    ScratchSnapshot,
    SquareInspection,
    StaticExchangeResult,
)
from .position import (
    STARTING_FEN,
    apply_move,
    legal_moves,
    normalize_move,
    parse_position,
    position_status,
)
from .scratch import ScratchBoard

__all__ = [
    "STARTING_FEN",
    "ChessCoreError",
    "CheckEvasion",
    "ColorName",
    "CurrentCheck",
    "ForcingMove",
    "ForcingMoveScan",
    "IllegalMoveError",
    "InvalidPositionError",
    "InvalidSquareError",
    "MoveIdentity",
    "MoveTransition",
    "PieceInfo",
    "PositionStatus",
    "ScratchBoard",
    "ScratchSnapshot",
    "SquareInspection",
    "StaticExchangeResult",
    "apply_move",
    "inspect_square",
    "legal_moves",
    "normalize_move",
    "parse_position",
    "position_status",
    "scan_agent_forcing_moves",
    "scan_opponent_forcing_moves",
    "static_exchange",
]
