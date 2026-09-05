"""One-turn smoke runner. Demo/diagram modes never call LM Studio."""

import argparse
import asyncio
import json
from dataclasses import asdict

from langchain_core.tracers.langchain import wait_for_all_tracers

from chess_core import STARTING_FEN, position_status
from harness.contracts import TurnRequest
from harness.model import LMStudioModel

from .config import AgentConfig
from .graph import AgentPlayer1


class DemoModel:
    """Scripted control-flow example, not a chess-playing model."""

    def __init__(self):
        self.responses = iter(
            [
                None,
                (
                    "scratch_play_move",
                    {
                        "move": "e4",
                        "justification": "Test whether e4 permits a forcing reply before preparing the defensive report.",
                    },
                ),
                (
                    "submit_defense_report",
                    {
                        "report": "Severity: None. No immediate defensive obligation was found in this scripted demonstration."
                    },
                ),
                (
                    "submit_attack_report",
                    {
                        "report": "Opportunity: None. No forcing opportunity was established in this scripted demonstration."
                    },
                ),
                (
                    "submit_move",
                    {
                        "move": "e4",
                        "justification": "The scripted example chooses e4 to demonstrate the final legal-move submission.",
                    },
                ),
            ]
        )

    async def complete(self, **kwargs):
        item = next(self.responses)
        text = (
            "Consider whether a central pawn move exposes an immediate threat."
            if item is None
            else (
                "<agent_tool_call>"
                + json.dumps({"tool": item[0], "arguments": item[1]})
                + "</agent_tool_call>"
            )
        )
        return {"status": "completed", "output_text": text}


async def run(args):
    if args.list_models:
        client = LMStudioModel()
        try:
            models = await client.client.models.list()
            print(json.dumps([model.id for model in models.data], indent=2))
        finally:
            await client.aclose()
        return
    config = (
        AgentConfig(model="scripted-demo")
        if args.demo or args.diagram
        else AgentConfig.from_env()
    )
    client = None if args.demo or args.diagram else LMStudioModel()
    agent = AgentPlayer1(client or DemoModel(), config)
    try:
        if args.diagram:
            print(agent.graph.get_graph().draw_mermaid())
            return
        if args.demo and args.fen != STARTING_FEN:
            raise ValueError("The scripted demo uses the starting position only.")
        request = TurnRequest(
            game_id=args.game_id,
            fen=args.fen,
            pgn=args.pgn,
            side=position_status(args.fen).side_to_move,
        )
        result = await agent.choose_move(request)
        print(json.dumps(asdict(result), indent=2))
    finally:
        if client:
            await client.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true")
    mode.add_argument("--diagram", action="store_true")
    mode.add_argument("--list-models", action="store_true")
    parser.add_argument("--fen", default=STARTING_FEN)
    parser.add_argument("--pgn", default="*")
    parser.add_argument("--game-id", default="localhost-smoke")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    finally:
        # Short-lived CLI processes should finish their queued trace uploads.
        wait_for_all_tracers()


if __name__ == "__main__":
    main()
