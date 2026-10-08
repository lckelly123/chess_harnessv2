from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import router


def test_delete_match_cascades_history_and_updates_folder_counts(repository, harnesses):
    folder = repository.create_folder("Keep this folder")
    for identifier in ("delete-me", "keep-me"):
        repository.create_match(identifier, *harnesses, folder_id=folder.id)
        repository.set_turn(identifier, "white", 1, "Baseline")
        repository.stop(identifier, "Finished testing")

    app = FastAPI()
    app.state.match_manager = SimpleNamespace(repository=repository)
    app.include_router(router)
    with TestClient(app) as client:
        response = client.delete("/api/matches/delete-me")
        assert response.status_code == 204 and not response.content
        assert client.get("/api/matches/delete-me").status_code == 404
        assert client.delete("/api/matches/delete-me").status_code == 404
        assert client.get("/api/matches").json()["total"] == 1
        folders = client.get("/api/folders").json()
        assert folders["totalMatches"] == 1
        assert folders["items"][0]["matchCount"] == 1
        assert folders["items"][0]["id"] == folder.id
    for table in ("positions", "events"):
        rows = repository._connection.execute(
            f"SELECT DISTINCT match_id FROM {table}"
        ).fetchall()
        assert [row["match_id"] for row in rows] == ["keep-me"]


def test_active_match_cannot_be_deleted(repository, harnesses):
    repository.create_match("active", *harnesses)
    app = FastAPI()
    app.state.match_manager = SimpleNamespace(repository=repository)
    app.include_router(router)
    with TestClient(app) as client:
        response = client.delete("/api/matches/active")
        assert response.status_code == 409
        assert "Stop this match" in response.json()["detail"]
        assert client.get("/api/matches/active").json()["status"] == "running"
        repository.stop("active", "Stopped by user")
        assert client.delete("/api/matches/active").status_code == 204
