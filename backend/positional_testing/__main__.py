"""Run one registered harness against a PostgreSQL library position."""

from __future__ import annotations

import argparse
import asyncio

from langchain_core.tracers.langchain import wait_for_all_tracers

from app.matches.catalog import (
    AGENT_PLAYER_1_ID,
    AGENT_PLAYER_2_ID,
    AGENT_PLAYER_3_ID,
    BASELINE_ID,
    HarnessCatalog,
)
from harness.model import LMStudioModel

from .runner import PositionalTestRunner

AGENT_ALIASES = {
    "baseline": BASELINE_ID,
    "agent_player_1": AGENT_PLAYER_1_ID,
    "agent_player_2": AGENT_PLAYER_2_ID,
    "agent_player_3": AGENT_PLAYER_3_ID,
    BASELINE_ID: BASELINE_ID,
    AGENT_PLAYER_1_ID: AGENT_PLAYER_1_ID,
    AGENT_PLAYER_2_ID: AGENT_PLAYER_2_ID,
    AGENT_PLAYER_3_ID: AGENT_PLAYER_3_ID,
}


def _agent_id(value: str) -> str:
    try:
        return AGENT_ALIASES[value.strip()]
    except KeyError as exc:
        choices = "baseline, agent_player_1, agent_player_2, or agent_player_3"
        raise argparse.ArgumentTypeError(f"agent must be {choices}") from exc


async def run(position_id: str, harness_id: str) -> None:
    model = LMStudioModel()
    try:
        result = await PositionalTestRunner(HarnessCatalog(model)).run_once(
            position_id,
            harness_id,
        )
        print(result.model_dump_json(by_alias=True, indent=2))
    finally:
        await model.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--position",
        required=True,
        help="Position UUID from the PostgreSQL library or positional-testing API.",
    )
    parser.add_argument(
        "--agent",
        required=True,
        type=_agent_id,
        metavar="{baseline,agent_player_1,agent_player_2,agent_player_3}",
        help="Harness to invoke once.",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args.position, args.agent))
    finally:
        wait_for_all_tracers()


if __name__ == "__main__":
    main()
