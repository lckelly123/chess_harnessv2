import json
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import JUSTIFICATION

from chess_core import STARTING_FEN, apply_move
from harness.baseline import BaselineConfig
from harness.baseline.prompts import build_input, load_instructions
from harness.baseline.state import initial_state
from harness.baseline.tools import submit_move, tool_schemas, validate_arguments
from harness.contracts import TurnRequest
from harness.protocol import ToolProtocolError

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "legacy_baseline_packets.json").read_text(
        encoding="utf-8"
    )
)


def test_tool_schema_matches_legacy_baseline():
    assert tool_schemas() == FIXTURE["tools"]
    assert len(tool_schemas()) == 1
    schema = tool_schemas()[0]
    assert schema["name"] == "submit_move"
    assert "enum" not in schema["parameters"]["properties"]["move"]
    assert schema["strict"]
    assert schema["parameters"]["additionalProperties"] is False


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["name"])
def test_dynamic_packet_matches_legacy_without_native_actions(case):
    state = initial_state(
        TurnRequest(
            game_id=case["name"], fen=case["fen"], pgn=case["pgn"], side=case["side"]
        )
    )
    state.update(history=case["history"], correction=case["correction"])
    assert build_input(state) == case["packet"]


def test_instructions_only_define_submit_move(request_position):
    instructions = load_instructions()
    schemas = json.loads(
        instructions.split("Tool schemas:\n\n```json\n")[1].split("```")[0]
    )
    assert [schema["name"] for schema in schemas] == ["submit_move"]
    assert "<agent_tool_call>" in instructions
    packet = build_input(initial_state(request_position))
    for forbidden in (
        "SEE",
        "Forcing-Move Scan",
        "Defense Report",
        "Attack Report",
        "Working Notes",
        "e2e4",
    ):
        assert forbidden not in packet


@pytest.mark.parametrize(
    "field", ["fen", "board", "positions", "position_id", "tool", "arguments", "action"]
)
def test_rejects_extra_arguments(field):
    with pytest.raises(ToolProtocolError):
        submit_move(
            STARTING_FEN,
            {"move": "e4", "justification": JUSTIFICATION, field: "injected"},
        )


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"move": "e4"},
        {"move": 42, "justification": JUSTIFICATION},
        {"move": "e4", "justification": "check"},
        [],
    ],
)
def test_argument_validation(args):
    with pytest.raises(ToolProtocolError):
        validate_arguments("submit_move", args)


def test_last_move_from_pgn_and_no_transient_boards(request_position):
    fen = apply_move(STARTING_FEN, "e4").fen_after
    state = initial_state(
        replace(request_position, fen=fen, pgn="1. e4 *", side="black")
    )
    assert state["last_move"] == "e4"
    assert "scratch_moves" not in state
    assert "defense_report" not in state
    assert "attack_report" not in state
    assert "## Last Move\n\n```text\ne4\n```" in build_input(state)


@pytest.mark.parametrize(
    "pgn", ["1. e4 *", "1. e5 *", '[Event "One"]\n\n*\n\n[Event "Two"]\n\n*']
)
def test_rejects_inconsistent_or_invalid_record(request_position, pgn):
    with pytest.raises(ValueError, match="PGN"):
        initial_state(replace(request_position, pgn=pgn))


def test_fen_only_and_custom_start_records(request_position):
    fen = "4k3/1P6/8/8/8/8/8/4K3 w - - 0 1"
    bare = initial_state(replace(request_position, fen=fen))
    pgn = f'[SetUp "1"]\n[FEN "{fen}"]\n\n*'
    with_record = initial_state(replace(request_position, fen=fen, pgn=pgn))
    assert bare["last_move"] == with_record["last_move"] == "None."
    assert bare["canonical_fen"] == with_record["canonical_fen"] == fen


@pytest.mark.parametrize(
    "fen,side",
    [
        (STARTING_FEN, "black"),
        ("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", "black"),
        ("not a FEN", "white"),
    ],
)
def test_invalid_turn_rejected_before_model(request_position, fen, side):
    with pytest.raises(ValueError):
        initial_state(replace(request_position, fen=fen, side=side))


def test_explicit_model_and_versioned_config(monkeypatch):
    monkeypatch.delenv("LMSTUDIO_MODEL", raising=False)
    with pytest.raises(ValueError, match="LMSTUDIO_MODEL"):
        BaselineConfig.from_env()
    monkeypatch.setenv("LMSTUDIO_MODEL", "local-model")
    monkeypatch.setenv("LMSTUDIO_REASONING_EFFORT", "high")
    config = BaselineConfig.from_env()
    assert config.model == "local-model"
    assert config.reasoning_effort == "high"
    assert config.prompt_version == "baseline-direct-submit-langgraph-v1"
    assert config.prompt_version != FIXTURE["prompt_version"]


@pytest.mark.parametrize(
    "name",
    [
        "max_output_tokens",
        "retry_max_output_tokens",
        "max_failed_tool_calls",
        "max_model_calls",
        "max_protocol_retries",
        "max_forced_retries",
        "history_event_limit",
    ],
)
def test_invalid_budgets(name):
    with pytest.raises(ValueError, match=name):
        BaselineConfig(model="test", **{name: -1})
