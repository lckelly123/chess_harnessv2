"""One-turn execution boundary for saved positional tests."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from app.matches.catalog import HarnessCatalog
from app.models import ModelSelection
from harness.contracts import TurnRequest
from harness.recording import current_recorder

from . import evaluation, run_repository
from .catalog import get_saved_position
from .models import SavedPositionMove, SavedPositionRun
from .recording import PassRecorder


class UnknownSavedPositionError(ValueError):
    """A requested position identifier is not in the PostgreSQL library."""


class PositionalTestRunner:
    """Run exactly one harness turn without creating or mutating a match."""

    def __init__(
        self,
        catalog: HarnessCatalog,
        *,
        id_factory: Callable[[], str] | None = None,
        repository=None,
        evaluator=None,
    ):
        self._catalog = catalog
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self.repository = repository or run_repository.RunRepository()
        self.evaluator = evaluator or evaluation.StockfishEvaluator()

    async def run_once(
        self,
        position_id: str,
        harness_id: str,
        model_selection: ModelSelection | None = None,
        *,
        queue_item: tuple[str, int] | None = None,
    ) -> SavedPositionRun:
        document = await run_in_threadpool(get_saved_position, position_id)
        if document is None:
            raise UnknownSavedPositionError(f"Unknown saved position: {position_id}")

        definition = self._catalog.definition(harness_id)
        position = document.position
        run_id = self._id_factory()
        config = {
            "harness_name": definition.name,
            "harness_version": definition.version,
        }
        if queue_item is not None:
            config.update(queue_id=queue_item[0], queue_ordinal=queue_item[1])
        requested_model = model_selection.model_id if model_selection else "qwen"
        await run_in_threadpool(
            self.repository.create,
            run_id,
            position.id,
            requested_model,
            definition.id,
            config,
            **({"queue_item": queue_item} if queue_item is not None else {}),
        )
        recorder = PassRecorder(self.repository, run_id)
        token = current_recorder.set(recorder)
        try:
            player, model_name = await self._catalog.create_player(
                harness_id,
                lambda: False,
                model_selection=model_selection,
            )
            settings = getattr(player, "config", None)
            if is_dataclass(settings):
                config.update(asdict(settings))
            await run_in_threadpool(
                self.repository.configure, run_id, model_name, config
            )
            decision = await player.choose_move(
                TurnRequest(
                    game_id=run_id,
                    fen=position.position.fen,
                    pgn=document.pgn,
                    side=position.side_to_move,
                    ply=position.move_count,
                )
            )
        except BaseException as exc:
            message = str(exc) or "Run interrupted before a move was submitted."
            try:
                await run_in_threadpool(recorder.fail, exc)
                await run_in_threadpool(self.repository.finish, run_id, error=message)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Could not persist failed positional run %s", run_id
                )
            raise
        finally:
            current_recorder.reset(token)

        # Grading is never visible to the agent and cannot change a successful
        # model turn into a model failure. Keep history polling until it finishes.
        await run_in_threadpool(self.repository.save_move, run_id, decision.move.uci)
        try:
            grade = await self.evaluator.evaluate(
                fen=position.position.fen, pgn=document.pgn, move_uci=decision.move.uci
            )
        except BaseException as exc:
            grade = {
                "evaluation": {
                    "status": "failed",
                    "policy_version": evaluation.POLICY_VERSION,
                    "error": str(exc) or "Evaluation interrupted.",
                }
            }
            await run_in_threadpool(
                self.repository.finish, run_id, move=decision.move.uci, grade=grade
            )
            if not isinstance(exc, Exception):
                raise
            logging.getLogger(__name__).exception(
                "Could not grade positional run %s", run_id
            )
        else:
            await run_in_threadpool(
                self.repository.finish, run_id, move=decision.move.uci, grade=grade
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
