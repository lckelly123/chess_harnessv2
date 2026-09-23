"""Extract pass notes and tool batches; never persist encrypted reasoning items."""

import json
import re
from datetime import UTC, datetime

from harness.model import visible_output


def now():
    return datetime.now(UTC)


class PassRecorder:
    def __init__(self, repository, run_id):
        self.repository = repository
        self.run_id = run_id
        self.number = 0
        self.current = None

    def save(self):
        if self.current is not None:
            self.repository.save_pass(self.current)

    def begin(self, state):
        self.number += 1
        self.current = dict(
            run_id=self.run_id,
            pass_number=self.number,
            phase=state.get("phase", "decide"),
            tool_calls=[],
            working_notes=None,
            status="running",
            error=None,
            started_at=now(),
            finished_at=None,
        )
        self.save()

    def response(self, response):
        text, reasoning = visible_output(response)
        notes, calls = [], []
        # Best-effort extraction also preserves valid portions of rejected output.
        for item in response.get("output", []):
            if item.get("type") != "function_call":
                continue
            try:
                arguments = item.get("arguments", {})
                value = (
                    json.loads(arguments) if isinstance(arguments, str) else arguments
                )
            except (ValueError, TypeError):
                value = None
            if item.get("name") == "agent_step" and isinstance(value, dict):
                if isinstance(value.get("running_thoughts"), str):
                    notes.append(value["running_thoughts"])
                actions = value.get("tool_calls")
                if isinstance(actions, list):
                    calls.extend(self.call(a, item.get("call_id")) for a in actions)
            else:
                calls.append(
                    self.call(
                        {"tool": item.get("name"), "arguments": value or arguments},
                        item.get("call_id"),
                    )
                )
        for content in re.findall(
            r"<running_thoughts>(.*?)</running_thoughts>", text, re.S
        ):
            notes.append(content.strip())
        for content in re.findall(
            r"<agent_tool_calls?>(.*?)</agent_tool_calls?>", text, re.S
        ):
            try:
                value = json.loads(content)
            except ValueError:
                continue
            calls.extend(
                self.call(a) for a in (value if isinstance(value, list) else [value])
            )
        if not notes:
            # Older harnesses expose prose before their text-tool block.
            prose = re.sub(r"<agent_tool_calls?>.*", "", text, flags=re.S).strip()
            notes = [value for value in (reasoning, prose) if value]
        self.current["working_notes"] = "\n\n".join(notes) or None
        self.current["tool_calls"] = calls
        self.save()

    @staticmethod
    def call(value, call_id=None):
        if not isinstance(value, dict):
            value = {"arguments": value}
        return dict(
            call_id=call_id,
            tool_name=value.get("tool", "unknown"),
            arguments=value.get("arguments"),
            result=None,
            error=None,
            executed=False,
        )

    def tool_started(self, function, args, kwargs):
        if args:  # Baseline submit_move(fen, arguments).
            name, arguments = "submit_move", args[1]
            context = {"canonical_fen": args[0]}
        else:
            name, arguments = kwargs["name"], kwargs["arguments"]
            context = {
                k: kwargs[k]
                for k in ("canonical_fen", "scratch_moves", "active_branch_id")
                if k in kwargs
            }
        calls = self.current["tool_calls"]
        index = next(
            (
                i
                for i, c in enumerate(calls)
                if c["tool_name"] == name
                and not c["executed"]
                and c["arguments"] == arguments
            ),
            None,
        )
        if index is None:
            index = next(
                (
                    i
                    for i, c in enumerate(calls)
                    if c["tool_name"] == name and not c["executed"]
                ),
                None,
            )
        if index is None:
            index = len(calls)
            calls.append(self.call({"tool": name, "arguments": arguments}))
        calls[index].update(
            executed=True,
            board_context=context,
            execution_order=1 + sum(c["executed"] for c in calls),
        )
        self.save()
        return index

    def tool_finished(self, index, *, result=None, error=None):
        # Tool helpers also return harness scratch state. Persist the exposed
        # result/decision rather than copying the entire internal state per call.
        if isinstance(result, dict):
            if "result" in result:
                result = result["result"]
            elif result.get("terminal"):
                result = {k: result[k] for k in ("decision", "report") if k in result}
        self.current["tool_calls"][index].update(result=result, error=error)
        self.save()

    def state(self, before, after):
        if self.current is None:
            return
        events = after.get("events", [])[len(before.get("events", [])) :]
        for event in events:
            if event.get("type") == "forced_tool_retry":
                self.current.update(status="failed", error=event["reason"])
            if event.get("type") != "tool_call":
                continue
            index = event.get("batch_index", 0)
            if index >= len(self.current["tool_calls"]):
                continue
            call = self.current["tool_calls"][index]
            if event.get("rolled_back"):
                call.update(rolled_back=True, result=None)
            if event.get("ok") is False:
                call["error"] = event.get("result_summary")
                self.current.update(status="failed", error=call["error"])
        if not after.get("pending_tools") and not after.get("pending_tool"):
            if self.current["status"] == "running":
                self.current["status"] = "completed"
            self.current["finished_at"] = self.current["finished_at"] or now()
        self.save()

    def fail(self, error, *, rollback=False):
        if self.current is None or self.current["finished_at"] is not None:
            return
        if rollback:
            for call in self.current["tool_calls"]:
                if call["executed"] and not call["error"]:
                    call.update(rolled_back=True, result=None)
        self.current.update(
            status="failed", error=str(error) or "Run interrupted.", finished_at=now()
        )
        self.save()
