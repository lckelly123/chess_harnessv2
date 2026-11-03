"""Extend the ordinary pass observer without altering harness decisions."""

from copy import deepcopy

from positional_testing.recording import PassRecorder

from .storage import timestamp, validate_capture


class GrpoRecorder(PassRecorder):
    def __init__(self, repository, run_id, store, name, trajectory):
        super().__init__(repository, run_id)
        self.store, self.name, self.trajectory = store, name, trajectory
        self.capture = self.request = None
        self.rejected = False
        self.rejection_reason = None
        self._flushed = set()

    def begin(self, state):
        self.flush()
        self.capture = self.request = None
        self.rejected = False
        self.rejection_reason = None
        super().begin(state)
        self.store.update(self.name, currentCall=self.number)

    def capture_input(self, payload):
        self.request = deepcopy(payload)
        super().capture_input(payload)

    def capture_tokens(self, capture):
        validate_capture(capture)
        self.capture = deepcopy(capture)

    def rejection(self, reason):
        self.rejected, self.rejection_reason = True, str(reason)

    def state(self, before, after):
        for event in after.get("events", [])[len(before.get("events", [])) :]:
            if event.get("type") in {"forced_tool_retry", "response_retry"}:
                self.rejection(event["reason"])
        super().state(before, after)
        if self.current is not None and self.current["finished_at"] is not None:
            self.flush()

    def fail(self, error, *, rollback=False):
        super().fail(error, rollback=rollback)
        self.flush()

    def flush(self):
        with self._write_lock:
            if self.current is None or self.number in self._flushed:
                return
            if self.capture is None:
                if self.request is None:
                    return
                capture = {
                    "input": None,
                    "prompt_token_ids": [],
                    "generated_response": "",
                    "completion_token_ids": [],
                    "old_logprobs": [],
                    "sampling_logprobs": [],
                    "finish_reason": "capture_error",
                    "status": "failed",
                    "error": self.current.get("error")
                    or "Token capture was not returned; this call is not trainable.",
                }
            else:
                capture = deepcopy(self.capture)
            record = {
                **capture,
                "call_index": self.number,
                "run_id": self.run_id,
                "request": self.request,
                "harness_rejected": self.rejected,
                "rejection_reason": self.rejection_reason,
                "tool_requests": deepcopy(self.current["tool_calls"]),
                "harness_status": self.current["status"],
                "harness_error": self.current.get("error"),
                "recorded_at": timestamp(),
                "capture_valid": self.capture is not None,
            }
            self.store.append_call(self.name, self.trajectory, record)
            self._flushed.add(self.number)
