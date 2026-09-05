import json
from pathlib import Path

import pytest

from harness.agent_player_1.prompts import build_input, forced_input, load_instructions
from harness.agent_player_1.state import initial_state
from harness.agent_player_1.tools import tool_schemas
from harness.contracts import TurnRequest

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "legacy_packets.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("phase", ["defense", "attack", "synthesis"])
def test_tool_schema_parity(phase):
    assert tool_schemas(phase) == FIXTURE["tools"][phase]


@pytest.mark.parametrize("phase", ["defense", "attack", "synthesis"])
def test_static_instruction_parity(phase):
    assert load_instructions(phase) == FIXTURE["instructions"][phase]


@pytest.mark.parametrize(
    "trigger", ["reasoning_only_response", "reasoning_budget_exhausted"]
)
def test_forced_retry_packet_parity(trigger):
    assert (
        forced_input(
            "# Position packet\n", "Check the central pawn advance.", trigger=trigger
        )
        == FIXTURE["retries"][trigger]
    )


@pytest.mark.parametrize("phase", ["defense", "attack", "synthesis"])
@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["name"])
def test_dynamic_packet_parity(case, phase):
    state = initial_state(
        TurnRequest(
            game_id=case["name"], fen=case["fen"], pgn=case["pgn"], side=case["side"]
        )
    )
    state.update(
        phase=phase,
        scratch_moves=case["scratch_moves"],
        history=case["history"],
        correction=case["correction"],
        defense_report=FIXTURE["defense_report"],
        attack_report=FIXTURE["attack_report"],
    )
    assert build_input(state) == case["packets"][phase]
