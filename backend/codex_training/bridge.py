"""One run's pending model call. All mutation happens on the backend event loop."""

import asyncio
import hashlib
import json
import secrets
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from harness.contracts import HarnessError

TERMINAL = frozenset({"completed", "failed", "cancelled"})


class SubmissionConflict(ValueError):
    """A response does not belong to the pending pass, or changes an accepted one."""


@dataclass
class SubmittedResponse:
    response: str
    reasoning_text: str


@dataclass
class PendingPass:
    id: str
    number: int
    model_input: dict[str, Any]
    response: asyncio.Future[SubmittedResponse]
    token: str


class RunSession:
    def __init__(self, run_id: str, *, pass_timeout: float):
        self.run_id = run_id
        self.token = secrets.token_urlsafe(32)
        self.pass_timeout = pass_timeout
        self.status = "starting"
        self.error: str | None = None
        self.move: str | None = None
        self.cancel_requested = False
        self.pending: PendingPass | None = None
        self.pass_number = 0
        self.metadata: dict[str, Any] = {}
        self.position_id: str | None = None
        self.result: dict[str, Any] | None = None
        self.stop_error = "Codex training run stopped."
        self._pass_tokens: dict[str, str] = {}
        self._accepted: dict[str, str] = {}
        self._changed = asyncio.Event()

    def _notify(self):
        previous = self._changed
        self._changed = asyncio.Event()
        previous.set()

    def snapshot(self) -> dict[str, Any]:
        result = {
            "run_id": self.run_id,
            "status": self.status,
            "pass": None,
            "move": self.move,
            "error": self.error,
            "last_accepted_pass_id": next(reversed(self._accepted), None),
        }
        if self.status == "waiting" and self.pending is not None:
            result["pass"] = {
                "pass_id": self.pending.id,
                "pass_number": self.pending.number,
                "model_input": deepcopy(self.pending.model_input),
            }
        return result

    async def current(self, wait_seconds: float = 0) -> dict[str, Any]:
        """Wait for an actionable input or a terminal state, with bounded polling."""
        try:
            async with asyncio.timeout(wait_seconds):
                while self.status not in TERMINAL and self.status != "waiting":
                    await self._changed.wait()
        except TimeoutError:
            pass
        return self.snapshot()

    async def exchange(self, model_input: dict[str, Any]) -> SubmittedResponse:
        if self.cancel_requested or self.status in TERMINAL:
            raise HarnessError("Codex training run is no longer active.")
        if self.pending is not None:
            raise HarnessError("This run already has a pending model pass.")
        self.pass_number += 1
        pending = PendingPass(
            id=str(uuid4()),
            number=self.pass_number,
            model_input=deepcopy(model_input),
            response=asyncio.get_running_loop().create_future(),
            token=secrets.token_urlsafe(32),
        )
        self._pass_tokens[pending.token] = pending.id
        self.pending = pending
        self.status = "waiting"
        self._notify()
        try:
            return await asyncio.wait_for(pending.response, self.pass_timeout)
        except TimeoutError as exc:
            raise HarnessError(
                f"Codex did not submit pass {pending.number} within "
                f"{self.pass_timeout:g} seconds."
            ) from exc
        finally:
            self.pending = None
            if self.status not in TERMINAL:
                self.status = "processing"
            self._notify()

    def token_scope(self, token: str) -> str | None:
        if secrets.compare_digest(self.token.encode(), token.encode()):
            return None
        if token in self._pass_tokens:
            return self._pass_tokens[token]
        raise PermissionError("Invalid run or pass token.")

    def scoped_snapshot(self, scope: str | None):
        snapshot = self.snapshot()
        if scope is not None:
            if not snapshot["pass"] or snapshot["pass"]["pass_id"] != scope:
                return {"run_id": self.run_id, "status": "pass_finished", "pass": None}
        elif snapshot["pass"] and self.pending:
            snapshot["pass"]["pass_token"] = self.pending.token
        return snapshot

    def submit(self, pass_id: str, response: str, reasoning_text: str) -> bool:
        """Return False for an identical retry; never execute an accepted pass twice."""
        encoded = json.dumps([response, reasoning_text], ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if pass_id in self._accepted:
            if self._accepted[pass_id] != digest:
                raise SubmissionConflict("This pass already has a different response.")
            return False
        pending = self.pending
        if (
            self.cancel_requested
            or self.status != "waiting"
            or pending is None
            or pending.id != pass_id
            or pending.response.done()
        ):
            raise SubmissionConflict("This is not the run's pending pass.")
        self._accepted[pass_id] = digest
        self.status = "processing"
        pending.response.set_result(SubmittedResponse(response, reasoning_text))
        self._notify()
        return True

    def finish(self, status: str, *, error: str | None = None, move: str | None = None):
        if status not in TERMINAL:
            raise ValueError("Expected a terminal run status.")
        self.status, self.error, self.move = status, error, move
        self._notify()

    def cancel(self, error: str = "Codex training run stopped."):
        self.stop_error = error
        self.cancel_requested = True
        if self.pending is not None and not self.pending.response.done():
            self.status = "processing"
            self.pending.response.set_exception(HarnessError(error))
        self._notify()
