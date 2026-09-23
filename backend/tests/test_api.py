import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.matches.catalog import (
    AGENT_PLAYER_1_ID,
    AGENT_PLAYER_2_ID,
    AGENT_PLAYER_3_ID,
    BASELINE_ID,
    HARNESSES,
    HarnessCatalog,
    UnknownHarnessError,
)
from app.matches.manager import MatchSettings
from app.matches.repository import MatchRepository
from app.models import ModelSelection
from chess_core import normalize_move
from harness.contracts import MoveDecision


@pytest.fixture(autouse=True)
def position_library(library_rows):
    return library_rows


class SlowPlayer:
    async def choose_move(self, request):
        await asyncio.sleep(3600)


class OneShotPlayer:
    def __init__(self, catalog):
        self.catalog = catalog

    async def choose_move(self, request):
        self.catalog.one_shot_requests.append(request)
        return MoveDecision(
            move=normalize_move(request.fen, "e5"),
            justification="Advance the center pawn.",
            defense_report="No urgent defense.",
            attack_report="The pawn attacks the knight.",
        )


class FakeCatalog:
    def __init__(self):
        self._definitions = {item.id: item for item in HARNESSES}
        self.one_shot_requests = []
        self.model_selections = []

    def list(self):
        return list(self._definitions.values())

    def definition(self, harness_id):
        try:
            return self._definitions[harness_id]
        except KeyError as exc:
            raise UnknownHarnessError(f"Unknown harness version: {harness_id}") from exc

    async def create_players(
        self, white_id, black_id, cancellation_check, model_selection=None
    ):
        self.definition(white_id)
        self.definition(black_id)
        self.model_selections.append(model_selection)
        return SlowPlayer(), SlowPlayer(), "scripted-model"

    async def create_player(self, harness_id, cancellation_check, model_selection=None):
        self.definition(harness_id)
        self.model_selections.append(model_selection)
        return OneShotPlayer(self), "scripted-model"


def test_real_api_contract_and_stop(database_path) -> None:
    repository = MatchRepository(str(database_path))
    catalog = FakeCatalog()
    app = create_app(
        repository=repository,
        catalog=catalog,
        settings=MatchSettings(
            database_path=":memory:",
            max_active=1,
        ),
    )
    try:
        with TestClient(app) as client:
            health = client.get("/api/health")
            assert health.status_code == 200
            assert health.json()["dataSource"] == "sqlite"

            harnesses = client.get("/api/harnesses")
            assert harnesses.status_code == 200
            assert {item["id"] for item in harnesses.json()} == {
                BASELINE_ID,
                AGENT_PLAYER_1_ID,
                AGENT_PLAYER_2_ID,
                AGENT_PLAYER_3_ID,
            }

            positions = client.get("/api/positional-testing/positions")
            assert positions.status_code == 200
            assert (
                positions.json()["items"][0]["id"]
                == "5448280b-9d09-5211-97d3-ff1376d90797"
            )
            assert positions.json()["items"][0]["sideToMove"] == "white"
            assert positions.json()["items"][0]["position"]["san"] == "Bb4"
            assert positions.json()["items"][0]["split"] == "train"
            assert positions.json()["items"][0]["phase"] == "opening"

            run = client.post(
                "/api/positional-testing/runs",
                json={
                    "positionId": "5448280b-9d09-5211-97d3-ff1376d90797",
                    "harnessId": AGENT_PLAYER_1_ID,
                },
            )
            assert run.status_code == 200
            assert run.json()["positionId"] == "5448280b-9d09-5211-97d3-ff1376d90797"
            assert run.json()["harnessName"] == "Agent Player 1"
            assert run.json()["model"] == "scripted-model"
            assert run.json()["move"]["san"] == "e5"
            assert run.json()["attackReport"] == "The pawn attacks the knight."
            assert len(catalog.one_shot_requests) == 1
            assert catalog.one_shot_requests[0].ply == 10
            assert '[Result "*"]' in (catalog.one_shot_requests[0].pgn)

            folder_response = client.post(
                "/api/folders", json={"name": "Baseline comparisons"}
            )
            assert folder_response.status_code == 201
            folder = folder_response.json()
            assert folder["name"] == "Baseline comparisons"

            duplicate = client.post(
                "/api/folders", json={"name": "baseline COMPARISONS"}
            )
            assert duplicate.status_code == 409

            created = client.post(
                "/api/matches",
                json={
                    "whiteHarnessId": BASELINE_ID,
                    "blackHarnessId": AGENT_PLAYER_1_ID,
                    "folderId": folder["id"],
                },
            )
            assert created.status_code == 201
            assert created.json()["status"] == "running"
            assert created.json()["folder"]["id"] == folder["id"]
            match_id = created.json()["id"]

            conflict = client.post(
                "/api/matches",
                json={
                    "whiteHarnessId": BASELINE_ID,
                    "blackHarnessId": BASELINE_ID,
                },
            )
            assert conflict.status_code == 409

            stopped = client.post(f"/api/matches/{match_id}/stop")
            assert stopped.status_code == 200
            assert stopped.json()["status"] == "stopped"
            assert stopped.json()["result"] == "aborted"
            assert stopped.json()["terminationReason"] == "Stopped by the user."

            search = client.get("/api/matches", params={"query": "Agent Player 1"})
            assert search.status_code == 200
            assert search.json()["total"] == 1
            assert search.json()["items"][0]["id"] == match_id

            filtered = client.get("/api/matches", params={"folder_id": folder["id"]})
            assert filtered.status_code == 200
            assert filtered.json()["total"] == 1

            unfiled = client.patch(
                f"/api/matches/{match_id}/folder", json={"folderId": None}
            )
            assert unfiled.status_code == 200
            assert unfiled.json()["folder"] is None

            folders = client.get("/api/folders")
            assert folders.status_code == 200
            assert folders.json()["totalMatches"] == 1
            assert folders.json()["unfiledCount"] == 1
    finally:
        repository.close()


def test_rejects_unknown_harness(database_path) -> None:
    repository = MatchRepository(str(database_path))
    app = create_app(
        repository=repository,
        catalog=FakeCatalog(),
        settings=MatchSettings(database_path=":memory:"),
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/matches",
                json={
                    "whiteHarnessId": "missing",
                    "blackHarnessId": BASELINE_ID,
                },
            )
            assert response.status_code == 422

            positional_harness = client.post(
                "/api/positional-testing/runs",
                json={
                    "positionId": "5448280b-9d09-5211-97d3-ff1376d90797",
                    "harnessId": "missing",
                },
            )
            assert positional_harness.status_code == 422

            positional_position = client.post(
                "/api/positional-testing/runs",
                json={
                    "positionId": "missing",
                    "harnessId": BASELINE_ID,
                },
            )
            assert positional_position.status_code == 404
    finally:
        repository.close()


@pytest.mark.parametrize("model_id", ["qwen", "gpt-terra"])
def test_both_endpoints_forward_model_selection(database_path, model_id):
    repository = MatchRepository(str(database_path))
    catalog = FakeCatalog()
    app = create_app(repository=repository, catalog=catalog)
    selection = {"modelId": model_id, "reasoningEffort": "medium"}
    try:
        with TestClient(app) as client:
            match = client.post(
                "/api/matches",
                json={
                    "whiteHarnessId": BASELINE_ID,
                    "blackHarnessId": AGENT_PLAYER_2_ID,
                    "modelSelection": selection,
                },
            )
            assert match.status_code == 201
            client.post(f"/api/matches/{match.json()['id']}/stop")
            run = client.post(
                "/api/positional-testing/runs",
                json={
                    "positionId": "5448280b-9d09-5211-97d3-ff1376d90797",
                    "harnessId": AGENT_PLAYER_2_ID,
                    "modelSelection": selection,
                },
            )
            assert run.status_code == 200
            assert catalog.model_selections == [
                ModelSelection(model_id=model_id),
                ModelSelection(model_id=model_id),
            ]
    finally:
        repository.close()


@pytest.mark.parametrize(
    "selection",
    [
        {"modelId": "unregistered", "reasoningEffort": "medium"},
        {"modelId": "gpt-terra", "reasoningEffort": "high"},
        {"modelId": "gpt-terra", "baseUrl": "https://untrusted.invalid"},
        {},
    ],
)
def test_invalid_model_selection_is_rejected_before_run(database_path, selection):
    repository = MatchRepository(str(database_path))
    catalog = FakeCatalog()
    app = create_app(repository=repository, catalog=catalog)
    try:
        with TestClient(app) as client:
            for path, payload in (
                (
                    "/api/matches",
                    {
                        "whiteHarnessId": BASELINE_ID,
                        "blackHarnessId": AGENT_PLAYER_2_ID,
                    },
                ),
                (
                    "/api/positional-testing/runs",
                    {
                        "positionId": "5448280b-9d09-5211-97d3-ff1376d90797",
                        "harnessId": AGENT_PLAYER_2_ID,
                    },
                ),
            ):
                response = client.post(
                    path, json={**payload, "modelSelection": selection}
                )
                assert response.status_code == 422
            assert catalog.model_selections == []
            assert repository.list_matches().total == 0
    finally:
        repository.close()


def test_missing_openai_key_returns_actionable_error_without_local_fallback(
    database_path,
):
    async def unexpected_local_discovery():
        pytest.fail("GPT must not discover or fall back to a local model")

    repository = MatchRepository(str(database_path))
    catalog = HarnessCatalog(object(), model_resolver=unexpected_local_discovery)
    app = create_app(repository=repository, catalog=catalog)
    try:
        with TestClient(app) as client:
            for path, payload in (
                (
                    "/api/matches",
                    {
                        "whiteHarnessId": BASELINE_ID,
                        "blackHarnessId": AGENT_PLAYER_2_ID,
                    },
                ),
                (
                    "/api/positional-testing/runs",
                    {
                        "positionId": "5448280b-9d09-5211-97d3-ff1376d90797",
                        "harnessId": AGENT_PLAYER_2_ID,
                    },
                ),
            ):
                response = client.post(
                    path,
                    json={**payload, "modelSelection": {"modelId": "gpt-terra"}},
                )
                assert response.status_code == 503
                assert "OPENAI_API_KEY" in response.json()["detail"]
            assert repository.list_matches().total == 0
    finally:
        repository.close()
