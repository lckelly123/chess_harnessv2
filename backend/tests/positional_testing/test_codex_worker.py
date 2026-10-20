import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

from codex_training.worker import (
    CodexPassError,
    WindowsWorker,
    codex_command,
    resolve_codex,
)


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


@pytest.mark.parametrize("exit_code", [0, 1])
def test_worker_keeps_redacted_actual_error_after_process_exit(
    tmp_path, monkeypatch, exit_code
):
    events = [
        {
            "type": "item.completed",
            "item": {"type": "reasoning", "text": "PRIVATE CONTENT"},
        },
        {"type": "error", "message": "temporary disconnect"},
        {
            "type": "turn.failed",
            "error": {
                "code": "quota",
                "message": "Usage exhausted run-secret pass-secret worker-secret sk-private-key",
            },
        },
    ]
    child = tmp_path / "failed.py"
    child.write_text(
        "import sys\nsys.stdin.read()\n"
        "sys.stderr.write('WARN Shell snapshot not supported yet for PowerShell\\n')\n"
        f"sys.stdout.write({''.join(json.dumps(event) + chr(10) for event in events)!r})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "codex_training.worker.codex_command",
        lambda *a, **kw: [sys.executable, str(child)],
    )

    async def run():
        worker = WindowsWorker(
            backend_url="http://127.0.0.1:8000",
            token="worker-secret",
            executable="fixture",
            model="fixture",
            effort="xhigh",
            cli_version="fixture",
            runtime=tmp_path,
        )

        async def report(*args, **kwargs):
            pass

        monkeypatch.setattr(worker, "report", report)
        try:
            with pytest.raises(
                CodexPassError, match="quota: Usage exhausted"
            ) as caught:
                await worker.run_pass(
                    {
                        "run_id": "fixture-run",
                        "run_token": "run-secret",
                        "model": "fixture",
                        "reasoning_effort": "xhigh",
                    },
                    {
                        "pass": {
                            "pass_id": "pass",
                            "pass_number": 1,
                            "pass_token": "pass-secret",
                        }
                    },
                )
            log = (tmp_path / "logs/fixture-run/pass-001.jsonl").read_text()
            assert "Usage exhausted" in log and "[redacted]" in log
            assert "PowerShell" not in str(caught.value)
            for secret in (
                "run-secret",
                "pass-secret",
                "worker-secret",
                "sk-private-key",
                "PRIVATE CONTENT",
            ):
                assert secret not in log + str(caught.value)
        finally:
            await worker.client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "after_status", ["processing", "waiting", "completed", "failed", "cancelled"]
)
def test_cli_failure_after_accepted_submission_preserves_backend_outcome(
    tmp_path, monkeypatch, after_status
):
    async def run():
        worker = WindowsWorker(
            backend_url="http://127.0.0.1:8000",
            token="fixture",
            executable="fixture",
            model="fixture",
            effort="xhigh",
            cli_version="fixture",
            runtime=tmp_path,
        )
        snapshots = iter(
            [
                {"status": "waiting", "pass": {"pass_id": "assigned"}},
                {
                    "status": after_status,
                    "pass": {"pass_id": "next"} if after_status == "waiting" else None,
                    "last_accepted_pass_id": "assigned",
                },
                {"status": "completed"},
            ]
        )
        reports = []

        async def request(*args, **kwargs):
            return next(snapshots)

        async def run_pass(*args):
            raise CodexPassError("CLI disconnected after submission")

        async def report(*args):
            reports.append(args)

        monkeypatch.setattr(worker, "request", request)
        monkeypatch.setattr(worker, "run_pass", run_pass)
        monkeypatch.setattr(worker, "report", report)
        try:
            await worker.execute({"run_id": "run", "run_token": "token"})
            assert reports == []
            assert worker.active_run is None
        finally:
            await worker.client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("last_accepted", [None, "earlier-pass"])
def test_cli_failure_without_matching_backend_receipt_is_reported(
    tmp_path, monkeypatch, last_accepted
):
    async def run():
        worker = WindowsWorker(
            backend_url="http://127.0.0.1:8000",
            token="fixture",
            executable="fixture",
            model="fixture",
            effort="xhigh",
            cli_version="fixture",
            runtime=tmp_path,
        )
        reports = []

        async def request(*args, **kwargs):
            return {
                "status": "waiting",
                "pass": {"pass_id": "assigned"},
                "last_accepted_pass_id": last_accepted,
            }

        async def run_pass(*args):
            raise CodexPassError("Actual provider failure")

        async def report(*args):
            reports.append(args)

        monkeypatch.setattr(worker, "request", request)
        monkeypatch.setattr(worker, "run_pass", run_pass)
        monkeypatch.setattr(worker, "report", report)
        try:
            await worker.execute({"run_id": "run", "run_token": "token"})
            assert reports[0][1:] == ("Stopped", "Actual provider failure")
        finally:
            await worker.client.aclose()

    asyncio.run(run())
