import asyncio

from fastapi.testclient import TestClient

from app.main import create_app
from app.matches.catalog import (
    AGENT_PLAYER_1_ID,
    BASELINE_ID,
    HARNESSES,
    UnknownHarnessError,
)
from app.matches.manager import MatchSettings
from app.matches.repository import MatchRepository


class SlowPlayer:
    async def choose_move(self, request):
        await asyncio.sleep(3600)


class FakeCatalog:
    def __init__(self):
        self._definitions = {item.id: item for item in HARNESSES}

    def list(self):
        return list(self._definitions.values())

    def definition(self, harness_id):
        try:
            return self._definitions[harness_id]
        except KeyError as exc:
            raise UnknownHarnessError(f"Unknown harness version: {harness_id}") from exc

    async def create_players(self, white_id, black_id, cancellation_check):
        self.definition(white_id)
        self.definition(black_id)
        return SlowPlayer(), SlowPlayer(), "scripted-model"


def test_real_api_contract_and_stop(database_path) -> None:
    repository = MatchRepository(str(database_path))
    app = create_app(
        repository=repository,
        catalog=FakeCatalog(),
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
            }

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
    finally:
        repository.close()
