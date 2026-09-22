"""One pass per node invocation; every repeat is a graph edge."""

from collections.abc import Callable

from harness.contracts import HarnessError, TurnCancelled
from harness.model import Model, NativeToolTurn, visible_output
from harness.protocol import ToolProtocolError

from .config import AgentConfig
from .prompt_builder import build_prompt
from .protocol import (
    AGENT_STEP,
    agent_step_schema,
    function_calls,
    parse_agent_response,
    replayable_output,
    tool_output,
)
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

    def _retry(self, state, message, *, protocol_error, trigger):
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
            "pending_running_thoughts": "",
            "pending_call_id": None,
            "next_step": state["phase"],
            "forced_retry": True,
            "retry_output": "",
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
            native_turn=NativeToolTurn(
                tools=[agent_step_schema()],
                function_name=AGENT_STEP,
                history=state["native_history"],
            ),
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
                    "native_tool_calls": function_calls(response),
                },
            ],
        }
        if response.get("status") in {"failed", "cancelled"}:
            raise HarnessError(f"Model response status: {response['status']}.")
        output_items = replayable_output(response)
        previous_ids = {
            item["call_id"]
            for item in state["native_history"]
            if item.get("type") == "function_call"
        }
        repeated_id = any(
            isinstance(call.get("call_id"), str) and call["call_id"] in previous_ids
            for call in function_calls(response)
        )
        if repeated_id:
            output_items = []
        if output_items:
            current["native_history"] = [
                *state["native_history"],
                {"role": "user", "content": prompt.dynamic_input},
                *output_items,
            ]
        try:
            parsed = parse_agent_response(response)
            if repeated_id:
                raise ToolProtocolError("A native call_id cannot be reused.")
            calls = []
            for parsed_call in parsed.tool_calls:
                call = dict(parsed_call)
                call["arguments"] = validate_arguments(
                    phase, call["tool"], call["arguments"]
                )
                calls.append(call)
            validate_tool_batch(calls)
        except ToolProtocolError as exc:
            details = response.get("incomplete_details") or {}
            exhausted = details.get("reason") == "max_output_tokens"
            trigger = (
                "reasoning_budget_exhausted"
                if exhausted
                else "invalid_native_tool_call"
            )
            if output_items:
                current["native_history"] = [
                    *current["native_history"],
                    *[
                        tool_output(
                            call["call_id"],
                            {"ok": False, "error": str(exc), "executed": False},
                        )
                        for call in function_calls(response)
                    ],
                ]
            return self._retry(
                current,
                str(exc),
                protocol_error=not exhausted,
                trigger=trigger,
            )
        if state["tool_calls"] + len(calls) > self.config.max_tool_calls:
            raise HarnessError(f"{phase} exceeded its tool-call limit.")
        current.update(
            pending_running_thoughts=parsed.running_thoughts,
            pending_call_id=parsed.call_id,
            pending_tools=calls,
            tool_calls=state["tool_calls"] + len(calls),
        )
        if any(call["tool"] == TERMINAL_TOOLS[phase] for call in calls):
            # Terminal tool validation is part of the submission edge; it has
            # its own LangSmith tool span without another orchestration loop.
            return self._execute(current)
        return {**current, "next_step": f"{phase}_tools"}

    def _complete_step(self, state: TurnState, result):
        call_id = state["pending_call_id"]
        if not call_id:
            raise HarnessError("Tool batch has no native call_id.")
        return {
            "native_history": [*state["native_history"], tool_output(call_id, result)],
            "pending_tools": [],
            "pending_running_thoughts": "",
            "pending_call_id": None,
            "forced_retry": False,
            "forced_retries": 0,
            "retry_output": "",
            "retry_trigger": "",
            "correction": "",
        }

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
                    "call_id": state["pending_call_id"],
                    "running_thoughts": state["pending_running_thoughts"],
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
                    **{key: value for key, value in event.items() if key != "result"},
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
                "call_id": state["pending_call_id"],
                "running_thoughts": state["pending_running_thoughts"],
                "arguments": dict(call["arguments"]),
                "ok": False,
                "result_summary": str(exc),
            }
            batch_events = [*rolled_back, failed_event]
            attempted_indices = {event["batch_index"] for event in batch_events}
            for index, skipped in indexed_calls:
                if index not in attempted_indices:
                    batch_events.append(
                        {
                            "type": "tool_call",
                            "phase": state["phase"],
                            "batch_index": index,
                            "call_id": state["pending_call_id"],
                            "tool": skipped["tool"],
                            "arguments": dict(skipped["arguments"]),
                            "ok": False,
                            "executed": False,
                            "result_summary": "Not executed because the batch was rejected.",
                        }
                    )
            batch_events.sort(key=lambda event: event["batch_index"])
            return {
                **state,
                **self._complete_step(
                    state,
                    {
                        "ok": False,
                        "error": str(exc),
                        "committed": False,
                        "running_thoughts": state["running_thoughts"],
                        "results": batch_events,
                    },
                ),
                "rejected_calls": rejected,
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
            }

        attempted_events.sort(key=lambda event: event["batch_index"])
        current = {
            **state,
            **self._complete_step(
                state,
                {
                    "ok": True,
                    "committed": True,
                    "running_thoughts": state["pending_running_thoughts"],
                    "results": attempted_events,
                },
            ),
            "running_thoughts": state["pending_running_thoughts"],
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
