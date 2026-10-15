"""Windows host worker: python -m codex_training.worker (uses saved Codex login)."""

import argparse
import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from .teacher import TEACHER_PROMPT

LOG = logging.getLogger(__name__)
BACKEND = Path(__file__).resolve().parents[1]
RUNTIME = BACKEND.parent / ".runtime"
TERMINAL = {"completed", "failed", "cancelled"}


def resolve_codex(explicit=None):
    """Prefer the newest installed native CLI; preserve an explicit override."""
    override = explicit or os.getenv("CODEX_CLI_PATH")
    if override:
        candidates = [str(override)]
    else:
        candidates = [shutil.which("codex.exe") or shutil.which("codex")]
        local = os.getenv("LOCALAPPDATA")
        if os.name == "nt" and local:
            candidates.extend(
                str(path)
                for path in (Path(local) / "OpenAI/Codex/bin").glob("*/codex.exe")
            )
    versions = []
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    for executable in dict.fromkeys(candidate for candidate in candidates if candidate):
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                **flags,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        version = result.stdout.strip()
        match = re.search(r"\b(\d+)\.(\d+)\.(\d+)", version)
        if result.returncode == 0 and match:
            versions.append((tuple(map(int, match.groups())), executable, version))
    if not versions:
        raise ValueError(
            "No working Codex CLI found. Install it or set CODEX_CLI_PATH."
        )
    _, executable, version = max(versions, key=lambda item: item[0])
    return executable, version


def codex_command(executable, workspace, *, model, effort, python=sys.executable):
    """Arguments, never a shell string. Each invocation starts a new conversation."""
    config = {
        "approval_policy": "never",
        "web_search": "disabled",
        "features.shell_tool": False,
        "features.apps": False,
        "features.plugins": False,
        "features.multi_agent": False,
        "features.remote_plugin": False,
        "features.code_mode": False,
        "project_doc_max_bytes": 0,
        "model_reasoning_effort": effort,
        "mcp_servers.chess.command": python,
        "mcp_servers.chess.args": ["-m", "codex_training.mcp_server"],
        "mcp_servers.chess.cwd": str(BACKEND),
        "mcp_servers.chess.env_vars": [
            "CHESS_RUN_ID",
            "CHESS_RUN_TOKEN",
            "CHESS_PASS_ID",
            "CHESS_BACKEND_URL",
        ],
        "mcp_servers.chess.required": True,
        "mcp_servers.chess.startup_timeout_sec": 30,
        "mcp_servers.chess.tool_timeout_sec": 45,
        "mcp_servers.chess.tools.get_current_pass.output_token_limit": 64000,
    }
    command = [
        executable,
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--cd",
        str(workspace),
        "--model",
        model,
    ]
    for key, value in config.items():
        command.extend(["-c", f"{key}={json.dumps(value)}"])
    return [*command, "-"]


async def terminate_tree(process):
    if process.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        await killer.wait()
    else:
        process.kill()
    await process.wait()


class WindowsWorker:
    def __init__(
        self,
        *,
        backend_url,
        token,
        executable,
        model,
        effort,
        cli_version,
        runtime=RUNTIME,
        client=None,
    ):
        self.backend_url = backend_url
        self.token = token
        self.executable = executable
        self.model = model
        self.effort = effort
        self.runtime = Path(runtime)
        self.worker_id = str(uuid4())
        self.identity = {
            "worker_id": self.worker_id,
            "model": model,
            "reasoning_effort": effort,
            "cli_version": cli_version,
        }
        self.client = client or httpx.AsyncClient(
            base_url=backend_url, timeout=35, trust_env=False, follow_redirects=False
        )
        self.cancel = asyncio.Event()
        self.last_heartbeat = time.monotonic()
        self.active_run = None
        self.stop = asyncio.Event()

    async def request(self, method, path, *, token=None, **kwargs):
        result = await self.client.request(
            method,
            "/api/codex-training" + path,
            headers={"Authorization": f"Bearer {token or self.token}"},
            **kwargs,
        )
        result.raise_for_status()
        return result.json()

    async def heartbeat(self):
        while not self.stop.is_set():
            try:
                result = await self.request(
                    "POST", "/worker/heartbeat", json=self.identity
                )
                self.last_heartbeat = time.monotonic()
                if self.active_run and (
                    result["active_run_id"] != self.active_run
                    or result["cancel_requested"]
                ):
                    self.cancel.set()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {403, 409}:
                    LOG.error(
                        "Worker registration rejected (%s). Check the worker token or another running worker.",
                        exc.response.status_code,
                    )
                    self.cancel.set()
                    self.stop.set()
                    return
                LOG.warning("Backend unavailable; waiting to reconnect.")
            except httpx.HTTPError:
                LOG.warning("Backend unavailable; waiting to reconnect.")
            if time.monotonic() - self.last_heartbeat > 15:
                self.cancel.set()
            await asyncio.sleep(3)

    async def report(self, job, progress, error=None):
        return await self.request(
            "POST",
            f"/jobs/{job['run_id']}/progress",
            json={"worker_id": self.worker_id, "progress": progress, "error": error},
        )

    async def run_pass(self, job, current):
        assignment = current["pass"]
        pass_id = assignment["pass_id"]
        number = assignment["pass_number"]
        await self.report(job, f"Writing pass {number}")
        environment = dict(os.environ)
        environment.pop("CODEX_WORKER_TOKEN", None)
        environment.update(
            CHESS_RUN_ID=job["run_id"],
            CHESS_RUN_TOKEN=assignment["pass_token"],
            CHESS_PASS_ID=pass_id,
            CHESS_BACKEND_URL=self.backend_url,
        )
        sessions = self.runtime / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        logs = self.runtime / "logs" / job["run_id"]
        logs.mkdir(parents=True, exist_ok=True)
        # The harness input is fetched by MCP. No old Codex conversation is resumed.
        prompt = (
            TEACHER_PROMPT
            + "\n\nExecute only the assigned pass. Call get_current_pass, "
            "then submit_response once with this pass_id: " + pass_id + ". "
            "After acknowledgement, end your turn. Do not continue to the next pass. "
            "Use only the chess MCP tools. Do not use external engines, files, or web search.\n"
        )
        with tempfile.TemporaryDirectory(prefix="pass-", dir=sessions) as workspace:
            process = await asyncio.create_subprocess_exec(
                *codex_command(
                    self.executable,
                    workspace,
                    model=job["model"],
                    effort=job["reasoning_effort"],
                ),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                cwd=workspace,
                limit=2**20,
                **(
                    {"creationflags": subprocess.CREATE_NO_WINDOW}
                    if os.name == "nt"
                    else {}
                ),
            )
            stderr = []

            async def read_errors():
                while line := await process.stderr.readline():
                    text = line.decode("utf-8", errors="replace")
                    for secret in (
                        self.token,
                        job["run_token"],
                        assignment["pass_token"],
                    ):
                        text = text.replace(secret, "[redacted]")
                    stderr.append(text)
                    del stderr[:-25]

            async def read_events():
                with (logs / f"pass-{number:03d}.jsonl").open(
                    "a", encoding="utf-8"
                ) as log:
                    while line := await process.stdout.readline():
                        try:
                            event = json.loads(line)
                        except (ValueError, UnicodeDecodeError):
                            continue
                        # Keep operational metadata, not private reasoning/event transcripts.
                        item = event.get("item") or {}
                        safe = {
                            "type": event.get("type"),
                            "thread_id": event.get("thread_id"),
                            "item_type": item.get("type"),
                            "tool": item.get("tool"),
                            "status": item.get("status"),
                            "usage": event.get("usage"),
                        }
                        log.write(json.dumps(safe) + "\n")
                        log.flush()

            readers = [
                asyncio.create_task(read_errors()),
                asyncio.create_task(read_events()),
            ]
            try:
                process.stdin.write(prompt.encode("utf-8"))
                await process.stdin.drain()
                process.stdin.close()
                deadline = time.monotonic() + 870
                while process.returncode is None:
                    if self.cancel.is_set() or self.stop.is_set():
                        raise RuntimeError(
                            "Codex training run stopped or worker disconnected."
                        )
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            f"Codex timed out while writing pass {number}."
                        )
                    done, _ = await asyncio.wait(
                        readers, timeout=1, return_when=asyncio.FIRST_EXCEPTION
                    )
                    for reader in done:
                        if reader.exception():
                            raise reader.exception()
                    if all(reader.done() for reader in readers):
                        await asyncio.wait_for(process.wait(), 5)
                if process.returncode:
                    detail = "".join(stderr)[-1400:]
                    raise RuntimeError(
                        f"Codex exited with code {process.returncode}. {detail}"
                    )
            finally:
                await terminate_tree(process)
                await asyncio.gather(*readers, return_exceptions=True)
                (logs / f"pass-{number:03d}.stderr.log").write_text(
                    "".join(stderr), encoding="utf-8"
                )

    async def execute(self, job):
        self.active_run = job["run_id"]
        self.cancel.clear()
        path = f"/runs/{job['run_id']}/pass"
        try:
            while not self.cancel.is_set():
                current = await self.request(
                    "GET", path, token=job["run_token"], params={"wait_seconds": 25}
                )
                if current["status"] in TERMINAL:
                    return
                if not current.get("pass"):
                    await self.report(job, "Processing tools or grading the move")
                    continue
                assigned = current["pass"]["pass_id"]
                await self.run_pass(job, current)
                after = await self.request(
                    "GET", path, token=job["run_token"], params={"wait_seconds": 25}
                )
                if after.get("pass") and after["pass"]["pass_id"] == assigned:
                    raise RuntimeError(
                        "Codex exited without submitting its assigned pass. See worker logs."
                    )
            raise RuntimeError("Codex training run stopped.")
        except Exception as exc:
            LOG.error("Run %s: %s", job["run_id"], exc)
            try:
                await self.report(job, "Stopped", str(exc)[:2000])
            except httpx.HTTPError:
                LOG.warning(
                    "Could not report failure; backend watchdog will finish the run."
                )
        finally:
            self.active_run = None

    async def run(self):
        heartbeat = asyncio.create_task(self.heartbeat())
        try:
            while not self.stop.is_set():
                try:
                    result = await self.request(
                        "POST", "/worker/claim", json={"worker_id": self.worker_id}
                    )
                    if result["job"]:
                        await self.execute(result["job"])
                except httpx.HTTPError:
                    pass  # Heartbeat reports connectivity/authentication problems.
                await asyncio.sleep(2)
        finally:
            self.stop.set()
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            await self.client.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--codex", help="Override automatic installed CLI selection")
    parser.add_argument("--model", default=os.getenv("CODEX_TEACHER_MODEL"))
    parser.add_argument(
        "--reasoning-effort", default=os.getenv("CODEX_TEACHER_REASONING_EFFORT")
    )
    parser.add_argument("--runtime-dir", type=Path, default=RUNTIME)
    args = parser.parse_args()
    url = urlparse(args.backend_url)
    if (
        url.scheme not in {"http", "https"}
        or url.hostname not in {"localhost", "127.0.0.1", "::1"}
        or url.username
        or url.password
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        parser.error("Use a loopback backend origin.")
    try:
        executable, version = resolve_codex(args.codex)
    except ValueError as exc:
        parser.error(str(exc))
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    login = subprocess.run(
        [executable, "login", "status"], capture_output=True, timeout=20, **flags
    )
    if login.returncode:
        parser.error(
            "Codex is not signed in. Run codex login, then restart the worker."
        )
    codex_config = (
        Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    )
    config = (
        tomllib.loads(codex_config.read_text("utf-8")) if codex_config.exists() else {}
    )
    model = args.model or config.get("model")
    effort = args.reasoning_effort or config.get("model_reasoning_effort", "medium")
    if not model:
        parser.error("Set --model or choose a default model in Codex configuration.")
    if effort not in {"low", "medium", "high", "xhigh", "max", "ultra"}:
        parser.error("Choose a supported --reasoning-effort.")
    args.runtime_dir.mkdir(parents=True, exist_ok=True)
    token_path = args.runtime_dir / "worker.token"
    try:
        with token_path.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(48))
        token_path.chmod(0o600)
    except FileExistsError:
        pass
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    LOG.info("Windows worker ready: %s, reasoning %s (%s)", model, effort, version)
    worker = WindowsWorker(
        backend_url=args.backend_url,
        token=token_path.read_text("utf-8").strip(),
        executable=executable,
        model=model,
        effort=effort,
        cli_version=version,
        runtime=args.runtime_dir,
    )
    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        LOG.info("Worker stopped.")


if __name__ == "__main__":
    main()
