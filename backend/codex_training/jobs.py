"""UI jobs claimed by one authenticated Windows worker; chess stays in the backend."""

import asyncio
import os
import secrets
import time
from pathlib import Path

from .bridge import TERMINAL
from .service import RunCapacityError

WORKER_TTL = 30


def worker_token():
    configured = os.getenv("CODEX_WORKER_TOKEN", "")
    if configured:
        return configured
    path = os.getenv("CODEX_WORKER_TOKEN_FILE", "")
    try:
        return Path(path).read_text("utf-8").strip() if path else ""
    except OSError:
        return ""


class WorkerJobs:
    def __init__(self, training):
        self.training = training
        self.worker = None
        self.seen = 0.0
        self.jobs: dict[str, dict] = {}
        self.lock = asyncio.Lock()
        self.monitor = None

    def start(self):
        self.monitor = asyncio.create_task(self.watch(), name="codex-worker-watch")

    async def close(self):
        if self.monitor:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)

    def authenticate(self, authorization):
        expected = worker_token()
        supplied = (authorization or "").removeprefix("Bearer ")
        if not expected or not secrets.compare_digest(
            expected.encode(), supplied.encode()
        ):
            raise PermissionError("A valid Windows worker token is required.")

    def online(self):
        return bool(self.worker and time.monotonic() - self.seen < WORKER_TTL)

    def active_jobs(self):
        return [
            run_id
            for run_id in self.jobs
            if run_id in self.training.sessions
            and self.training.sessions[run_id].status not in TERMINAL
        ]

    def status(self):
        return {
            "configured": bool(worker_token()),
            "online": self.online(),
            "model": self.worker["model"] if self.worker else None,
            "reasoning_effort": self.worker["reasoning_effort"]
            if self.worker
            else None,
            "active_run_id": next(iter(self.active_jobs()), None),
        }

    def heartbeat(self, payload):
        if self.online() and self.worker["worker_id"] != payload["worker_id"]:
            raise RunCapacityError("Another Windows worker is already connected.")
        if self.worker and self.worker["worker_id"] != payload["worker_id"]:
            for run_id in self.active_jobs():
                self.training.sessions[run_id].cancel(
                    "The Windows Codex worker restarted. Saved passes are retained; run again."
                )
        self.worker = payload
        self.seen = time.monotonic()
        active = next(iter(self.active_jobs()), None)
        return {
            "active_run_id": active,
            "cancel_requested": bool(
                active and self.training.sessions[active].cancel_requested
            ),
        }

    async def enqueue(self, position_id):
        async with self.lock:
            if not self.online():
                raise RunCapacityError(
                    "Start the Windows Codex worker, then try again."
                )
            if self.active_jobs():
                raise RunCapacityError(
                    "Finish or stop the current Codex training run first."
                )
            worker = dict(self.worker)
            active = await self.training.start(
                position_id,
                model_label=worker["model"],
                pass_timeout=900,
                metadata={
                    "execution_mode": "codex_exec",
                    "context_mode": "fresh_per_pass",
                    "model_identity_source": "worker_cli_argument",
                    "teacher_model": worker["model"],
                    "teacher_reasoning_effort": worker["reasoning_effort"],
                    "codex_cli_version": worker["cli_version"],
                },
            )
            # Pruned terminal bridge sessions are already durable in run history.
            self.jobs = {
                k: v for k, v in self.jobs.items() if k in self.training.sessions
            }
            self.jobs[active.run_id] = {
                "worker_id": None,
                "progress": "Waiting for Codex",
            }
            return self.snapshot(active.run_id)

    def snapshot(self, run_id):
        if run_id not in self.jobs or run_id not in self.training.sessions:
            raise KeyError(
                "This live Codex job is no longer available. Open run history."
            )
        session = self.training.sessions[run_id]
        return {
            "run_id": run_id,
            "position_id": session.position_id,
            "status": session.status,
            "pass_number": session.pass_number,
            "progress": self.jobs[run_id]["progress"],
            "error": session.error,
            "result": session.result,
            "stopping": session.cancel_requested,
        }

    def claim(self, worker_id):
        if not self.online() or self.worker["worker_id"] != worker_id:
            raise PermissionError("Register this worker before claiming a run.")
        for run_id in self.active_jobs():
            job = self.jobs[run_id]
            if job["worker_id"] is None:
                job["worker_id"] = worker_id
                active = self.training.sessions[run_id]
                return {
                    "run_id": run_id,
                    "run_token": active.token,
                    "model": active.metadata["teacher_model"],
                    "reasoning_effort": active.metadata["teacher_reasoning_effort"],
                }
        return None

    def report(self, run_id, worker_id, *, progress, error=None):
        self.snapshot(run_id)
        if self.jobs[run_id]["worker_id"] != worker_id:
            raise PermissionError("This run belongs to a different worker.")
        self.jobs[run_id]["progress"] = progress
        active = self.training.sessions[run_id]
        if error and active.status not in TERMINAL:
            active.cancel(error)

    async def watch(self):
        while True:
            await asyncio.sleep(5)
            if not self.online():
                for run_id in self.active_jobs():
                    self.training.sessions[run_id].cancel(
                        "Windows Codex worker disconnected. Restart the worker and run again."
                    )
