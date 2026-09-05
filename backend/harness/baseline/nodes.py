"""One model call or submission check per invocation; repeats are graph edges."""

from collections.abc import Callable

from harness.contracts import HarnessError, TurnCancelled
from harness.model import Model, visible_output
from harness.prompting import forced_input
from harness.protocol import ToolProtocolError, ToolRejected, parse_tool_call

from .config import BaselineConfig
from .prompts import build_input, load_instructions
from .state import BaselineState
from .tools import submit_move, validate_arguments


class BaselineNodes:
    def __init__(
        self,
        model: Model,
        config: BaselineConfig,
        cancellation_check: Callable[[], bool] | None = None,
    ):
        self.model, self.config = model, config
        self.cancellation_check = cancellation_check

    def _check_cancelled(self):
        if self.cancellation_check and self.cancellation_check():
            raise TurnCancelled("Turn cancelled; no move submitted.")

    async def decide(self, state: BaselineState):
        self._check_cancelled()
        if state["model_calls"] >= self.config.max_model_calls:
            raise HarnessError("Baseline exceeded its model-call limit.")
        forced = state["forced_retry"]
        dynamic = build_input(state)
        if forced:
            dynamic = forced_input(
                dynamic,
                state["retry_output"],
                token_limit=self.config.max_output_tokens,
                trigger=state["retry_trigger"],
            )
        response = await self.model.complete(
            model=self.config.model,
            instructions=load_instructions(),
            dynamic_input=dynamic,
            reasoning_effort=self.config.retry_reasoning_effort
            if forced
            else self.config.reasoning_effort,
            max_output_tokens=self.config.retry_max_output_tokens
            if forced
            else self.config.max_output_tokens,
            forced_retry=forced,
        )
        self._check_cancelled()
        if response.get("status") in {"failed", "cancelled"}:
            raise HarnessError(f"LM Studio response status: {response['status']}.")
        text, reasoning = visible_output(response)
        current = {
            **state,
            "model_calls": state["model_calls"] + 1,
            "forced_retries": state["forced_retries"] + int(forced),
            "events": [
                *state["events"],
                {
                    "type": "model_output",
                    "forced_retry": forced,
                    "text": text,
                    "reasoning": reasoning,
                },
            ],
        }
        try:
            call = parse_tool_call(text)
            call["arguments"] = validate_arguments(call["tool"], call["arguments"])
        except ToolProtocolError as exc:
            exposed = "\n\n".join(value for value in (reasoning, text) if value)
            reasoning_only = bool(exposed) and "<agent_tool_call>" not in text
            errors = current["protocol_errors"] + int(not reasoning_only)
            if errors > self.config.max_protocol_retries:
                raise HarnessError(
                    f"Baseline exceeded its protocol retry limit: {exc}"
                ) from exc
            if current["forced_retries"] >= self.config.max_forced_retries:
                raise HarnessError(
                    f"Baseline exhausted forced-tool retries: {exc}"
                ) from exc
            details = response.get("incomplete_details") or {}
            usage = response.get("usage") or {}
            reasoning_tokens = (usage.get("output_tokens_details") or {}).get(
                "reasoning_tokens", 0
            ) or 0
            exhausted = (
                details.get("reason") == "max_output_tokens"
                or reasoning_tokens >= self.config.max_output_tokens
            )
            return {
                **current,
                "protocol_errors": errors,
                "pending_tool": None,
                "correction": str(exc),
                "next_step": "decide",
                "forced_retry": True,
                "retry_output": exposed or state["retry_output"],
                "retry_trigger": "reasoning_budget_exhausted"
                if exhausted
                else "reasoning_only_response",
                "events": [
                    *current["events"],
                    {"type": "forced_tool_retry", "reason": str(exc)},
                ],
            }
        return {**current, "pending_tool": call, "next_step": "validate_submission"}

    def validate_submission(self, state: BaselineState):
        self._check_cancelled()
        call = state["pending_tool"]
        if call is None or call["tool"] != "submit_move":
            raise HarnessError(
                "Baseline validation requires a pending submit_move call."
            )
        event = {
            "type": "tool_call",
            "tool": "submit_move",
            "justification": call["arguments"]["justification"],
            "arguments": {"move": call["arguments"]["move"]},
        }
        try:
            decision = submit_move(state["canonical_fen"], call["arguments"])
        except ToolRejected as exc:
            rejected = state["rejected_calls"] + 1
            if rejected >= self.config.max_failed_tool_calls:
                raise HarnessError(
                    f"Baseline reached its rejected-tool limit: {exc}"
                ) from exc
            event.update(ok=False, result_summary=str(exc))
            history = [*state["history"], event]
            limit = self.config.history_event_limit
            return {
                **state,
                "rejected_calls": rejected,
                "pending_tool": None,
                "next_step": "decide",
                "history": history[-limit:] if limit else [],
                "events": [*state["events"], event],
                # Preserve any previous reasoning/forced-retry state on rejection.
                "correction": "",
            }
        self._check_cancelled()
        event.update(ok=True, result=decision, result_summary="Submission accepted.")
        return {
            **state,
            "decision": decision,
            "pending_tool": None,
            "next_step": "end",
            "correction": "",
            "forced_retry": False,
            "forced_retries": 0,
            "retry_output": "",
            "events": [*state["events"], event],
        }
