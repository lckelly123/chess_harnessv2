"""One pass per node invocation; every repeat is a graph edge."""

import logging
from collections.abc import Callable

from harness.contracts import HarnessError, TurnCancelled
from harness.model import Model, visible_output
from harness.protocol import ToolProtocolError
from harness.recording import complete_pass, record_node, recorded_tool

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
    validate_tool_state,
)

logger = logging.getLogger(__name__)


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

    def _retry(self, state, message, *, protocol_error, failed_tool_index=None):
        logger.warning(
            "Rejected chess_harness response: game=%s ply=%s pass=%s "
            "retries_used=%s/%s reason=%s",
            state["game_id"],
            state["ply"],
            state["model_calls"],
            state["forced_retries"],
            self.config.max_response_retries,
            message,
        )
        if state["forced_retries"] >= self.config.max_response_retries:
            raise HarnessError(
                f"{state['phase']} exhausted {self.config.max_response_retries} "
                f"same-input retries: {message}"
            )
        return {
            **state,
            "protocol_errors": state["protocol_errors"] + int(protocol_error),
            "rejected_calls": state["rejected_calls"] + int(not protocol_error),
            "pending_tools": [],
            "pending_running_thoughts": "",
            "next_step": state["phase"],
            "forced_retry": True,
            "events": [
                *state["events"],
                {
                    "type": "response_retry",
                    "phase": state["phase"],
                    "reason": message,
                    "failed_tool_index": failed_tool_index,
                    "retry_number": state["forced_retries"] + 1,
                },
            ],
        }

    @record_node
    async def _model_pass(self, phase: Phase, state: TurnState):
        self._check_cancelled()
        if state["phase"] != phase:
            raise HarnessError("Graph routed to a phase inconsistent with its state.")
        if state["model_calls"] >= self.config.max_model_calls:
            raise HarnessError(f"{phase} exceeded its model-call limit.")
        forced = state["forced_retry"]
        pass_input = state["pass_input"]
        if pass_input is None:
            prompt = build_prompt(state)
            pass_input = {
                "instructions": prompt.instructions,
                "dynamic_input": prompt.dynamic_input,
            }
        response = await complete_pass(
            self.model,
            state,
            model=self.config.model,
            **pass_input,
            reasoning_effort=self.config.reasoning_effort,
            max_output_tokens=self.config.max_output_tokens,
            forced_retry=forced,
        )
        self._check_cancelled()
        text, reasoning = visible_output(response)
        current = {
            **state,
            "pass_input": pass_input,
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
            raise HarnessError(f"Model response status: {response['status']}.")
        if response.get("status") == "incomplete":
            reason = (response.get("incomplete_details") or {}).get("reason", "unknown")
            return self._retry(
                current,
                f"Incomplete model response: {reason}.",
                protocol_error=True,
            )
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
            return self._retry(
                current,
                str(exc),
                protocol_error=True,
            )
        if state["tool_calls"] + len(calls) > self.config.max_tool_calls:
            raise HarnessError(f"{phase} exceeded its tool-call limit.")
        current.update(
            pending_running_thoughts=parsed.running_thoughts,
            pending_tools=calls,
        )
        if any(call["tool"] == TERMINAL_TOOLS[phase] for call in calls):
            # Terminal tool validation is part of the submission edge; it has
            # its own LangSmith tool span without another orchestration loop.
            return self._execute(current)
        return {**current, "next_step": f"{phase}_tools"}

    @record_node
    def _execute(self, state: TurnState):
        self._check_cancelled()
        calls = state["pending_tools"]
        if not calls:
            raise HarnessError("Tool node has no pending tool calls.")

        # Validate the entire batch before calling or recording any tool. Failed
        # proposals keep their notes and calls only in the saved model response.
        for batch_index, call in enumerate(calls):
            try:
                validate_tool_state(
                    phase=state["phase"],
                    name=call["tool"],
                    arguments=call["arguments"],
                    canonical_fen=state["canonical_fen"],
                    scratch_moves=state["scratch_moves"],
                    tested_lines=state["tested_lines"],
                    active_branch_id=state["active_branch_id"],
                )
            except (ToolProtocolError, ToolRejected) as exc:
                return self._retry(
                    state,
                    str(exc),
                    protocol_error=isinstance(exc, ToolProtocolError),
                    failed_tool_index=batch_index,
                )

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
        for batch_index, call in ordered_calls:
            event = {
                "type": "tool_call",
                "phase": state["phase"],
                "batch_index": batch_index,
                "tool": call["tool"],
                "running_thoughts": state["pending_running_thoughts"],
                "arguments": dict(call["arguments"]),
            }
            result = recorded_tool(
                execute_tool,
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
        attempted_events.sort(key=lambda event: event["batch_index"])
        current = {
            **state,
            "pending_tools": [],
            "running_thoughts": state["pending_running_thoughts"],
            "pending_running_thoughts": "",
            "pass_input": None,
            "tool_calls": state["tool_calls"] + len(calls),
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
