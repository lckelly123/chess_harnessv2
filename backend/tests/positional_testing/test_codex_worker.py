import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

from codex_training.worker import WindowsWorker, codex_command, resolve_codex


@pytest.mark.skipif(os.name != "nt", reason="Windows desktop CLI discovery")
def test_newer_desktop_cli_wins_over_old_path_but_override_is_respected(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    newer = tmp_path / "OpenAI/Codex/bin/desktop-current/codex.exe"
    newer.parent.mkdir(parents=True)
    newer.touch()
    monkeypatch.setattr("codex_training.worker.shutil.which", lambda _: "old.exe")
    monkeypatch.setattr(
        "codex_training.worker.subprocess.run",
        lambda args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="codex-cli 0.162.0-alpha.17.2"
            if args[0] == str(newer)
            else "codex-cli 0.142.5",
        ),
    )
    assert resolve_codex()[0] == str(newer)
    assert resolve_codex("old.exe")[0] == "old.exe"


def test_codex_command_is_fresh_restricted_and_contains_no_credentials(tmp_path):
    command = codex_command(
        "codex.exe", tmp_path, model="fixture-model", effort="medium"
    )
    assert command[:2] == ["codex.exe", "exec"]
    assert "resume" not in command
    assert "--ignore-user-config" in command and "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    config = dict(part.split("=", 1) for part in command if "=" in part)
    assert config["features.shell_tool"] == "false"
    assert config["web_search"] == '"disabled"'
    assert config["mcp_servers.chess.required"] == "true"
    assert json.loads(config["mcp_servers.chess.env_vars"]) == [
        "CHESS_RUN_ID",
        "CHESS_RUN_TOKEN",
        "CHESS_PASS_ID",
        "CHESS_BACKEND_URL",
    ]


def test_worker_cancellation_terminates_child_and_reports_failure(
    tmp_path, monkeypatch
):
    child = tmp_path / "waiting.py"
    child.write_text(
        "import sys,time\nsys.stdin.read()\ntime.sleep(120)\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "codex_training.worker.codex_command",
        lambda *a, **kw: [sys.executable, str(child)],
    )

    async def exercise():
        worker = WindowsWorker(
            backend_url="http://127.0.0.1:8000",
            token="secret",
            executable="fixture",
            model="fixture-model",
            effort="medium",
            cli_version="fixture",
            runtime=tmp_path,
        )

        async def report(*args, **kwargs):
            pass

        monkeypatch.setattr(worker, "report", report)
        job = {
            "run_id": "fixture-run",
            "run_token": "run-secret",
            "model": "fixture-model",
            "reasoning_effort": "medium",
        }
        current = {
            "pass": {
                "pass_number": 1,
                "pass_id": "fixture-pass",
                "pass_token": "pass-secret",
            }
        }
        task = asyncio.create_task(worker.run_pass(job, current))
        try:
            await asyncio.sleep(0.5)
            worker.cancel.set()
            with pytest.raises(RuntimeError, match="stopped"):
                await asyncio.wait_for(task, 8)
            assert not list((tmp_path / "sessions").iterdir())
        finally:
            await worker.client.aclose()

    asyncio.run(exercise())
