from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_lists_harness_versions() -> None:
    response = client.get("/api/harnesses")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} >= {
        "agent-player-1-v1",
        "agent-player-1-graph",
    }


def test_searches_match_records() -> None:
    response = client.get("/api/matches", params={"query": "material baseline"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert all(
        "Material Baseline" in f'{item["white"]["name"]} {item["black"]["name"]}'
        for item in payload["items"]
    )


def test_starts_then_stops_mock_match() -> None:
    created = client.post(
        "/api/matches",
        json={
            "whiteHarnessId": "agent-player-1-graph",
            "blackHarnessId": "material-baseline",
        },
    )
    assert created.status_code == 201
    assert created.json()["status"] == "running"

    stopped = client.post(f'/api/matches/{created.json()["id"]}/stop')
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"
    assert stopped.json()["result"] == "aborted"
