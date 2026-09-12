"""One-turn execution boundary for saved positional tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from app.matches.catalog import HarnessCatalog
from harness.contracts import TurnRequest

from .catalog import POSITION_DIRECTORY, get_saved_position
from .models import SavedPositionMove, SavedPositionRun


class UnknownSavedPositionError(ValueError):
    """A requested saved-position identifier is not in the PGN catalog."""


class PositionalTestRunner:
    """Run exactly one harness turn without creating or mutating a match."""

    def __init__(
        self,
        catalog: HarnessCatalog,
        *,
        position_directory: Path = POSITION_DIRECTORY,
        id_factory: Callable[[], str] | None = None,
    ):
        self._catalog = catalog
        self._position_directory = position_directory
        self._id_factory = id_factory or (lambda: f"positional-test-{uuid4().hex[:12]}")

    async def run_once(
        self,
        position_id: str,
        harness_id: str,
    ) -> SavedPositionRun:
        document = get_saved_position(position_id, self._position_directory)
        if document is None:
            raise UnknownSavedPositionError(f"Unknown saved position: {position_id}")

        definition = self._catalog.definition(harness_id)
        player, model_name = await self._catalog.create_player(
            harness_id,
            lambda: False,
        )
        position = document.position
        run_id = self._id_factory()
        decision = await player.choose_move(
            TurnRequest(
                game_id=run_id,
                fen=position.position.fen,
                pgn=document.pgn,
                side=position.side_to_move,
                ply=position.move_count,
            )
        )
        return SavedPositionRun(
            run_id=run_id,
            position_id=position.id,
            position_name=position.name,
            harness_id=definition.id,
            harness_name=definition.name,
            harness_version=definition.version,
            model=model_name,
            side=position.side_to_move,
            ply=position.move_count,
            move=SavedPositionMove(**asdict(decision.move)),
            justification=decision.justification,
            defense_report=decision.defense_report,
            attack_report=decision.attack_report,
        )
