"""Turn-local hypothetical move state isolated from canonical matches."""

from __future__ import annotations

from .models import MoveTransition, ScratchSnapshot
from .position import apply_move, parse_position


class ScratchBoard:
    """A small mutable shell around immutable move transitions."""

    def __init__(self, canonical_fen: str) -> None:
        self._canonical_fen = parse_position(canonical_fen)
        self._current_fen = self._canonical_fen
        self._moves: list[MoveTransition] = []

    @property
    def canonical_fen(self) -> str:
        return self._canonical_fen

    @property
    def current_fen(self) -> str:
        return self._current_fen

    @property
    def moves(self) -> tuple[MoveTransition, ...]:
        return tuple(self._moves)

    def play(self, move_text: str) -> MoveTransition:
        transition = apply_move(self._current_fen, move_text)
        self._moves.append(transition)
        self._current_fen = transition.fen_after
        return transition

    def undo(self) -> MoveTransition | None:
        if not self._moves:
            return None
        transition = self._moves.pop()
        self._current_fen = transition.fen_before
        return transition

    def reset(self) -> None:
        self._moves.clear()
        self._current_fen = self._canonical_fen

    def snapshot(self) -> ScratchSnapshot:
        return ScratchSnapshot(
            status="active" if self._moves else "unused",
            canonical_fen=self._canonical_fen,
            current_fen=self._current_fen,
            moves=tuple(self._moves),
        )
