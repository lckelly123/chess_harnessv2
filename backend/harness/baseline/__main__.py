"""One-turn baseline runner. Demo and diagram modes never call LM Studio."""

import argparse
import asyncio
import json
from dataclasses import asdict

from langchain_core.tracers.langchain import wait_for_all_tracers

from chess_core import STARTING_FEN, position_status
from harness.contracts import TurnRequest
from harness.model import LMStudioModel

from .config import BaselineConfig
from .graph import BaselineAgent


class DemoModel:
    """Demonstrate reasoning -> forced retry -> legal submission, not chess quality."""

    def __init__(self):
        self.outputs = iter(
            [
                "Consider e4 to claim central space and open development.",
                "<agent_tool_call>"
                + json.dumps(
                    {
                        "tool": "submit_move",
                        "arguments": {
                            "move": "e4",
                            "justification": "The scripted baseline chooses e4 to demonstrate a legal direct submission.",
                        },
                    }
                )
                + "</agent_tool_call>",
            ]
        )

    async def complete(self, **kwargs):
        return {"status": "completed", "output_text": next(self.outputs)}


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
        BaselineConfig(model="scripted-demo")
        if args.demo or args.diagram
        else BaselineConfig.from_env()
    )
    client = None if args.demo or args.diagram else LMStudioModel()
    try:
        agent = BaselineAgent(client or DemoModel(), config)
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
            ply=args.ply,
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
    parser.add_argument("--game-id", default="baseline-localhost-smoke")
    parser.add_argument("--ply", type=int, default=0)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    finally:
        wait_for_all_tracers()


if __name__ == "__main__":
    main()
