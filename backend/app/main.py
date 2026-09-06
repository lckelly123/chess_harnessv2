"""FastAPI composition root for the local match desk."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from harness.model import LMStudioModel

from .matches.catalog import HarnessCatalog
from .matches.manager import MatchManager, MatchSettings
from .matches.repository import MatchRepository
from .routes import router


def create_app(
    *,
    repository: MatchRepository | None = None,
    catalog: HarnessCatalog | None = None,
    settings: MatchSettings | None = None,
) -> FastAPI:
    configured_settings = settings or MatchSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_repository = repository is None
        active_repository = repository or MatchRepository(
            configured_settings.database_path
        )
        active_repository.recover_interrupted()

        model_client = None
        active_catalog = catalog
        if active_catalog is None:
            model_client = LMStudioModel()
            active_catalog = HarnessCatalog(model_client)

        manager = MatchManager(active_repository, active_catalog, configured_settings)
        app.state.match_manager = manager
        try:
            yield
        finally:
            await manager.close()
            if model_client is not None:
                await model_client.aclose()
            if owns_repository:
                active_repository.close()

    application = FastAPI(
        title="Chess Harness v2 API",
        version="0.2.0",
        description="Local deterministic match runner for versioned agent harnesses.",
        lifespan=lifespan,
    )
    application.include_router(router)
    return application


app = create_app()
