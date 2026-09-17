"""One pass per node invocation; every repeat is a graph edge."""

from collections.abc import Callable

from harness.contracts import HarnessError, TurnCancelled
from harness.model import Model, visible_output
from harness.protocol import ToolProtocolError

from .config import AgentConfig
from .prompt_builder import build_prompt
from .protocol import parse_agent_response
from .state import Phase, TurnState
from .tools import (
    ANNOTATION_TOOLS,
    TERMINAL_TOOLS,
    ToolRejected,
    execute_tool,
    validate_arguments,
    validate_tool_batch,
)


class SynthesisNodes:
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
            "pending_tools": [],
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
        prompt = build_prompt(state)
        response = await self.model.complete(
            model=self.config.model,
            instructions=prompt.instructions,
            dynamic_input=prompt.dynamic_input,
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
            parsed = parse_agent_response(text)
            calls = []
            for parsed_call in parsed.tool_calls:
                call = dict(parsed_call)
                call["arguments"] = validate_arguments(
                    phase, call["tool"], call["arguments"]
                )
                calls.append(call)
            validate_tool_batch(calls)
        except ToolProtocolError as exc:
            reasoning_only = bool(exposed) and "<agent_tool_calls>" not in text
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
        if state["tool_calls"] + len(calls) > self.config.max_tool_calls:
            raise HarnessError(f"{phase} exceeded its tool-call limit.")
        current.update(
            running_thoughts=parsed.running_thoughts,
            pending_tools=calls,
            tool_calls=state["tool_calls"] + len(calls),
        )
        if any(call["tool"] == TERMINAL_TOOLS[phase] for call in calls):
            # Terminal tool validation is part of the submission edge; it has
            # its own LangSmith tool span without another orchestration loop.
            return self._execute(current)
        return {**current, "next_step": f"{phase}_tools"}

    def _execute(self, state: TurnState):
        self._check_cancelled()
        calls = state["pending_tools"]
        if not calls:
            raise HarnessError("Tool node has no pending tool calls.")

        indexed_calls = list(enumerate(calls))
        ordered_calls = sorted(
            indexed_calls,
            key=lambda item: item[1]["tool"] not in ANNOTATION_TOOLS,
        )
        scratch_moves = list(state["scratch_moves"])
        tested_lines = state["tested_lines"]
        active_branch_id = state["active_branch_id"]
        attempted_events = []
        decision = None
        try:
            for batch_index, call in ordered_calls:
                event = {
                    "type": "tool_call",
                    "phase": state["phase"],
                    "batch_index": batch_index,
                    "tool": call["tool"],
                    "running_thoughts": state["running_thoughts"],
                    "arguments": dict(call["arguments"]),
                }
                result = execute_tool(
                    phase=state["phase"],
                    name=call["tool"],
                    arguments=call["arguments"],
                    canonical_fen=state["canonical_fen"],
                    side=state["side"],
                    scratch_moves=scratch_moves,
                    tested_lines=tested_lines,
                    active_branch_id=active_branch_id,
                    langsmith_extra={"name": call["tool"]},
                )
                scratch_moves = result["scratch_moves"]
                tested_lines = result["tested_lines"]
                active_branch_id = result["active_branch_id"]
                decision = result.get("decision", decision)
                event.update(
                    ok=True,
                    result=result.get("result", {"decision": result.get("decision")}),
                    result_summary=result.get("result_summary", "Submission accepted."),
                )
                attempted_events.append(event)
                self._check_cancelled()
        except ToolRejected as exc:
            rejected = state["rejected_calls"] + 1
            if rejected >= self.config.max_failed_tool_calls:
                raise HarnessError(
                    f"{state['phase']} reached its rejected-tool limit: {exc}"
                ) from exc
            rollback_summary = f"Rolled back because the tool batch was rejected: {exc}"
            rolled_back = [
                {
                    **event,
                    "ok": False,
                    "rolled_back": True,
                    "result_summary": rollback_summary,
                }
                for event in attempted_events
            ]
            failed_event = {
                "type": "tool_call",
                "phase": state["phase"],
                "batch_index": batch_index,
                "tool": call["tool"],
                "running_thoughts": state["running_thoughts"],
                "arguments": dict(call["arguments"]),
                "ok": False,
                "result_summary": str(exc),
            }
            batch_events = [*rolled_back, failed_event]
            batch_events.sort(key=lambda event: event["batch_index"])
            return {
                **state,
                "rejected_calls": rejected,
                "pending_tools": [],
                "next_step": state["phase"],
                "latest_tool_results": [
                    {
                        "tool": event["tool"],
                        "ok": False,
                        "result_summary": event["result_summary"],
                    }
                    for event in batch_events
                ],
                "history": [*state["history"], *batch_events][
                    -self.config.history_event_limit :
                ],
                "events": [*state["events"], *batch_events],
                "correction": "",
            }

        attempted_events.sort(key=lambda event: event["batch_index"])
        current = {
            **state,
            "pending_tools": [],
            "scratch_moves": scratch_moves,
            "tested_lines": tested_lines,
            "active_branch_id": active_branch_id,
            "latest_tool_results": [
                {
                    "tool": event["tool"],
                    "ok": True,
                    "result_summary": event["result_summary"],
                }
                for event in attempted_events
            ],
            "forced_retry": False,
            "forced_retries": 0,
            "retry_output": "",
            "correction": "",
            "history": [*state["history"], *attempted_events][
                -self.config.history_event_limit :
            ],
            "events": [*state["events"], *attempted_events],
        }
        if decision is not None:
            return {**current, "decision": decision, "next_step": "end"}
        return {**current, "next_step": state["phase"]}

    async def synthesis(self, state: TurnState):
        return await self._model_pass("synthesis", state)

    def synthesis_tools(self, state: TurnState):
        return self._execute(state)
