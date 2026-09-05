"""One pass per node invocation; every repeat is a graph edge."""

from collections.abc import Callable

from harness.contracts import HarnessError, TurnCancelled
from harness.model import Model, visible_output
from harness.protocol import parse_tool_call

from .config import AgentConfig
from .prompts import build_input, forced_input, load_instructions
from .state import Phase, TurnState, phase_state
from .tools import (
    TERMINAL_TOOLS,
    ToolProtocolError,
    ToolRejected,
    execute_tool,
    validate_arguments,
)


class PhaseNodes:
    def __init__(
        self,
        model: Model,
        config: AgentConfig,
        cancellation_check: Callable[[], bool] | None = None,
    ):
        self.model, self.config = model, config
        self.cancellation_check = cancellation_check

    def _check_cancelled(self):
        if self.cancellation_check and self.cancellation_check():
            raise TurnCancelled("Turn cancelled; no move submitted.")

    def _retry(self, state, message, output, *, protocol_error, trigger):
        errors = state["protocol_errors"] + int(protocol_error)
        if errors > self.config.max_protocol_retries:
            raise HarnessError(
                f"{state['phase']} exceeded its protocol retry limit: {message}"
            )
        if state["forced_retries"] >= self.config.max_forced_retries:
            raise HarnessError(
                f"{state['phase']} exhausted forced-tool retries: {message}"
            )
        return {
            **state,
            "protocol_errors": errors,
            "correction": message,
            "pending_tool": None,
            "next_step": state["phase"],
            "forced_retry": True,
            # Keep the original reasoning when a subsequent forced pass is empty.
            "retry_output": output or state["retry_output"],
            "retry_trigger": trigger,
            "events": [
                *state["events"],
                {
                    "type": "forced_tool_retry",
                    "phase": state["phase"],
                    "reason": message,
                },
            ],
        }

    async def _model_pass(self, phase: Phase, state: TurnState):
        self._check_cancelled()
        if state["phase"] != phase:
            raise HarnessError("Graph routed to a phase inconsistent with its state.")
        if state["model_calls"] >= self.config.max_model_calls:
            raise HarnessError(f"{phase} exceeded its model-call limit.")
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
            instructions=load_instructions(phase),
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
        text, reasoning = visible_output(response)
        current = {
            **state,
            "model_calls": state["model_calls"] + 1,
            "forced_retries": state["forced_retries"] + int(forced),
            "events": [
                *state["events"],
                {
                    "type": "model_output",
                    "phase": phase,
                    "forced_retry": forced,
                    "text": text,
                    "reasoning": reasoning,
                },
            ],
        }
        if response.get("status") in {"failed", "cancelled"}:
            raise HarnessError(f"LM Studio response status: {response['status']}.")
        exposed = "\n\n".join(value for value in (reasoning, text) if value)
        try:
            call = parse_tool_call(text)
            call["arguments"] = validate_arguments(
                phase, call["tool"], call["arguments"]
            )
        except ToolProtocolError as exc:
            reasoning_only = bool(exposed) and "<agent_tool_call>" not in text
            details = response.get("incomplete_details") or {}
            usage = response.get("usage") or {}
            reasoning_tokens = (usage.get("output_tokens_details") or {}).get(
                "reasoning_tokens", 0
            ) or 0
            exhausted = (
                details.get("reason") == "max_output_tokens"
                or reasoning_tokens >= self.config.max_output_tokens
            )
            trigger = (
                "reasoning_budget_exhausted" if exhausted else "reasoning_only_response"
            )
            return self._retry(
                current,
                str(exc),
                exposed,
                protocol_error=not reasoning_only,
                trigger=trigger,
            )
        if state["tool_calls"] >= self.config.max_tool_calls:
            raise HarnessError(f"{phase} exceeded its tool-call limit.")
        current.update(pending_tool=call, tool_calls=state["tool_calls"] + 1)
        if call["tool"] == TERMINAL_TOOLS[phase]:
            # Terminal tool validation is part of the submission edge; it has
            # its own LangSmith tool span without another orchestration loop.
            return self._execute(current)
        return {**current, "next_step": f"{phase}_tools"}

    def _execute(self, state: TurnState):
        self._check_cancelled()
        call = state["pending_tool"]
        if call is None:
            raise HarnessError("Tool node has no pending tool call.")
        event = {
            "type": "tool_call",
            "phase": state["phase"],
            "tool": call["tool"],
            "justification": call["arguments"].get("justification", ""),
            "arguments": {
                k: v for k, v in call["arguments"].items() if k != "justification"
            },
        }
        try:
            result = execute_tool(
                phase=state["phase"],
                name=call["tool"],
                arguments=call["arguments"],
                canonical_fen=state["canonical_fen"],
                side=state["side"],
                scratch_moves=state["scratch_moves"],
                langsmith_extra={"name": call["tool"]},
            )
        except ToolRejected as exc:
            rejected = state["rejected_calls"] + 1
            if rejected >= self.config.max_failed_tool_calls:
                raise HarnessError(
                    f"{state['phase']} reached its rejected-tool limit: {exc}"
                ) from exc
            event.update(ok=False, result_summary=str(exc))
            return {
                **state,
                "rejected_calls": rejected,
                "pending_tool": None,
                "next_step": state["phase"],
                "history": [*state["history"], event][
                    -self.config.history_event_limit :
                ],
                "events": [*state["events"], event],
                "correction": "",
            }
        self._check_cancelled()
        event.update(
            ok=True,
            result=result,
            result_summary=result.get("result_summary", "Submission accepted."),
        )
        current = {
            **state,
            "pending_tool": None,
            "forced_retry": False,
            "forced_retries": 0,
            "retry_output": "",
            "correction": "",
            "events": [*state["events"], event],
        }
        if result["terminal"]:
            if state["phase"] == "synthesis":
                return {**current, "decision": result["decision"], "next_step": "end"}
            next_phase = "attack" if state["phase"] == "defense" else "synthesis"
            return {
                **current,
                **phase_state(next_phase),
                f"{state['phase']}_report": result["report"],
            }
        return {
            **current,
            "scratch_moves": result["scratch_moves"],
            "next_step": state["phase"],
            "history": [*state["history"], event][-self.config.history_event_limit :],
        }

    async def defense(self, state: TurnState):
        return await self._model_pass("defense", state)

    async def attack(self, state: TurnState):
        return await self._model_pass("attack", state)

    async def synthesis(self, state: TurnState):
        return await self._model_pass("synthesis", state)

    def defense_tools(self, state: TurnState):
        return self._execute(state)

    def attack_tools(self, state: TurnState):
        return self._execute(state)

    def synthesis_tools(self, state: TurnState):
        return self._execute(state)
