import json
from copy import deepcopy

import pytest

from chess_core import STARTING_FEN
from harness.contracts import TurnRequest

DEFENSE = "Severity: None. No immediate defensive obligation was established by the reviewed position."
ATTACK = "Opportunity: Practical. The central pawn advance develops space without a verified forced gain."
JUSTIFICATION = "Test whether the central pawn advance allows a forcing reply before ranking candidates."
RUNNING_THOUGHTS = "The central pawn advance is the current candidate. Its strongest reply remains to be tested."


def call(name, **arguments):
    return {
        "status": "completed",
        "output_text": "<agent_tool_call>"
        + json.dumps({"tool": name, "arguments": arguments})
        + "</agent_tool_call>",
    }


def thoughtful_call(name, *, running_thoughts=RUNNING_THOUGHTS, **arguments):
    return thoughtful_batch(
        {"tool": name, "arguments": arguments},
        running_thoughts=running_thoughts,
    )


def thoughtful_batch(*calls, running_thoughts=RUNNING_THOUGHTS):
    return {
        "status": "completed",
        "output_text": (
            f"<running_thoughts>{running_thoughts}</running_thoughts>"
            "<agent_tool_calls>" + json.dumps(list(calls)) + "</agent_tool_calls>"
        ),
    }


def finish():
    return [
        call("submit_defense_report", report=DEFENSE),
        call("submit_attack_report", report=ATTACK),
        call("submit_move", move="e4", justification=JUSTIFICATION),
    ]


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def complete(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(autouse=True)
def offline_tracing(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


@pytest.fixture
def request_position():
    return TurnRequest(game_id="test-game", fen=STARTING_FEN, pgn="*", side="white")
