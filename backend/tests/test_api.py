import asyncio

from fastapi.testclient import TestClient

from app.main import create_app
from app.matches.catalog import (
    AGENT_PLAYER_1_ID,
    AGENT_PLAYER_2_ID,
    BASELINE_ID,
    HARNESSES,
    UnknownHarnessError,
)
from app.matches.manager import MatchSettings
from app.matches.repository import MatchRepository
from chess_core import normalize_move
from harness.contracts import MoveDecision


class SlowPlayer:
    async def choose_move(self, request):
        await asyncio.sleep(3600)


class OneShotPlayer:
    def __init__(self, catalog):
        self.catalog = catalog

    async def choose_move(self, request):
        self.catalog.one_shot_requests.append(request)
        return MoveDecision(
            move=normalize_move(request.fen, "Qxe3+"),
            justification="Wins the bishop with check.",
            defense_report="No urgent defense.",
            attack_report="Capture e3 with check.",
        )


class FakeCatalog:
    def __init__(self):
        self._definitions = {item.id: item for item in HARNESSES}
        self.one_shot_requests = []

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

    async def create_player(self, harness_id, cancellation_check):
        self.definition(harness_id)
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
            }

            positions = client.get("/api/positional-testing/positions")
            assert positions.status_code == 200
            assert positions.json()["items"][0]["id"] == "before_queen_blunder"
            assert positions.json()["items"][0]["sideToMove"] == "black"
            assert positions.json()["items"][0]["position"]["san"] == "Be3"

            run = client.post(
                "/api/positional-testing/runs",
                json={
                    "positionId": "before_queen_blunder",
                    "harnessId": AGENT_PLAYER_1_ID,
                },
            )
            assert run.status_code == 200
            assert run.json()["positionId"] == "before_queen_blunder"
            assert run.json()["harnessName"] == "Agent Player 1"
            assert run.json()["model"] == "scripted-model"
            assert run.json()["move"]["san"] == "Qxe3+"
            assert run.json()["attackReport"] == "Capture e3 with check."
            assert len(catalog.one_shot_requests) == 1
            assert catalog.one_shot_requests[0].ply == 23
            assert '[Event "Agent Player 1 Queen Blunder Test"]' in (
                catalog.one_shot_requests[0].pgn
            )

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
                    "positionId": "before_queen_blunder",
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
