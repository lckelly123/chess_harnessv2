"""Application-level task ownership, admission control, and cancellation."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from uuid import uuid4

from app.models import MatchDetail

from .catalog import HarnessCatalog
from .repository import MatchRepository, UnknownFolderError
from .runner import MatchRunner


class MatchConflictError(RuntimeError):
    """The local worker has reached its configured active-match limit."""


@dataclass(frozen=True, slots=True)
class MatchSettings:
    database_path: str = "data/chess-harness.sqlite3"
    max_active: int = 1

    def __post_init__(self):
        if self.max_active < 1:
            raise ValueError("max_active must be positive.")

    @classmethod
    def from_env(cls) -> MatchSettings:
        return cls(
            database_path=os.getenv(
                "MATCH_DATABASE_PATH", "data/chess-harness.sqlite3"
            ),
            max_active=int(os.getenv("MATCH_MAX_ACTIVE", "1")),
        )


class MatchManager:
    def __init__(
        self,
        repository: MatchRepository,
        catalog: HarnessCatalog,
        settings: MatchSettings,
    ):
        self.repository = repository
        self.catalog = catalog
        self.settings = settings
        self._runner = MatchRunner(repository)
        self._tasks: dict[str, tuple[asyncio.Task[None], asyncio.Event]] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        white_id: str,
        black_id: str,
        folder_id: str | None = None,
    ) -> MatchDetail:
        async with self._lock:
            if self.repository.active_count() >= self.settings.max_active:
                raise MatchConflictError(
                    "A match is already running. Stop it before starting another."
                )
            if folder_id is not None and not self.repository.folder_exists(folder_id):
                raise UnknownFolderError(f"Unknown game folder: {folder_id}")

            white_definition = self.catalog.definition(white_id)
            black_definition = self.catalog.definition(black_id)
            cancelled = asyncio.Event()
            white, black, _model_name = await self.catalog.create_players(
                white_id,
                black_id,
                cancelled.is_set,
            )
            match_id = f"match-{uuid4().hex[:12]}"
            match = self.repository.create_match(
                match_id,
                white_definition,
                black_definition,
                folder_id,
            )
            task = asyncio.create_task(
                self._execute(
                    match_id,
                    white=white,
                    black=black,
                    white_name=white_definition.name,
                    black_name=black_definition.name,
                    cancelled=cancelled,
                ),
                name=f"match-runner:{match_id}",
            )
            self._tasks[match_id] = (task, cancelled)
            return match

    async def _execute(self, match_id: str, **kwargs) -> None:
        try:
            await self._runner.run(match_id, **kwargs)
        except asyncio.CancelledError:
            self.repository.stop(match_id, "Stopped by the user.")
        except Exception as exc:
            message = str(exc).strip() or "Unexpected match runner failure."
            self.repository.fail(match_id, f"{type(exc).__name__}: {message}"[:1000])
        finally:
            self._tasks.pop(match_id, None)

    async def stop(self, match_id: str) -> MatchDetail | None:
        match = self.repository.get_match(match_id)
        if match is None:
            return None
        if match.status in {"queued", "running"}:
            task_entry = self._tasks.get(match_id)
            if task_entry is not None:
                task, cancelled = task_entry
                cancelled.set()
                task.cancel()
            self.repository.stop(match_id, "Stopped by the user.")
        return self.repository.get_match(match_id)

    async def close(self) -> None:
        entries = list(self._tasks.items())
        for match_id, (task, cancelled) in entries:
            cancelled.set()
            self.repository.stop(match_id, "Backend shut down during the match.")
            task.cancel()
        if entries:
            await asyncio.gather(
                *(task for _match_id, (task, _cancelled) in entries),
                return_exceptions=True,
            )
        self._tasks.clear()
