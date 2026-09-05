"""Domain-specific failures raised by deterministic chess operations."""

from __future__ import annotations


class ChessCoreError(ValueError):
    """Base class for errors that callers may translate at system boundaries."""


class InvalidPositionError(ChessCoreError):
    """Raised when a FEN cannot represent a valid position."""


class IllegalMoveError(ChessCoreError):
    """Raised when move text is malformed, ambiguous, or illegal."""


class InvalidSquareError(ChessCoreError):
    """Raised when a square is not in algebraic form, such as ``e4``."""
