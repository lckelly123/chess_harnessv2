"""Model.complete implementation whose response arrives through the MCP bridge."""

import asyncio
from typing import Any

from harness.contracts import HarnessError
from harness.model import NativeToolTurn
from harness.recording import current_recorder

from . import PROTOCOL_VERSION, PROVIDER
from .bridge import RunSession
from .teacher import TEACHER_PROMPT, teacher_metadata


class CodexModel:
    def __init__(self, session: RunSession):
        self.session = session

    async def complete(
        self,
        *,
        model: str,
        instructions: str,
        dynamic_input: str,
        reasoning_effort: str,
        max_output_tokens: int,
        forced_retry: bool,
        native_turn: NativeToolTurn | None = None,
    ) -> dict[str, Any]:
        if native_turn is not None:
            raise HarnessError(
                "The Codex adapter supports the chess_harness text protocol."
            )
        # This is the exact harness packet delivered by MCP, not a claim to capture
        # Codex's private prompt, hidden reasoning, or independently configured settings.
        payload = {
            "provider": PROVIDER,
            "protocol_version": PROTOCOL_VERSION,
            "capture_scope": "harness_exchange",
            "model": model,
            "model_identity_source": self.session.metadata.get(
                "model_identity_source", "caller_label"
            ),
            "input": [
                {"role": "developer", "content": instructions},
                {"role": "user", "content": dynamic_input},
            ],
            "forced_retry": forced_retry,
            "requested_settings": {
                "reasoning_effort": reasoning_effort,
                "max_output_tokens": max_output_tokens,
            },
            "teacher_instructions": TEACHER_PROMPT,
            "teacher": teacher_metadata(),
            "execution": self.session.metadata,
        }
        recorder = current_recorder.get()
        if recorder is not None:
            await asyncio.to_thread(recorder.capture_input, payload)
        submission = await self.session.exchange(payload)
        # An envelope for the existing parser/recorder. The submitted string is
        # preserved verbatim; no fabricated token usage or private reasoning fields.
        result = {
            "provider": PROVIDER,
            "capture_scope": "harness_exchange",
            "status": "completed",
            "reasoning_origin": "authored_explanation",
            "output": [
                {
                    "type": "reasoning",
                    "content": [
                        {"type": "reasoning_text", "text": submission.reasoning_text}
                    ],
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": submission.response}],
                },
            ],
        }
        if recorder is not None:
            await asyncio.to_thread(recorder.capture_output, result)
        return result
