"""Two-node baseline topology and the caller-facing one-move adapter."""

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from chess_core import normalize_move
from harness.contracts import HarnessError, MoveDecision, TurnRequest
from harness.model import Model

from .config import BaselineConfig
from .nodes import BaselineNodes
from .state import BaselineState, initial_state


def route(state: BaselineState) -> str:
    return state["next_step"]


def build_graph(
    model: Model,
    config: BaselineConfig,
    cancellation_check: Callable[[], bool] | None = None,
):
    nodes = BaselineNodes(model, config, cancellation_check)
    graph = StateGraph(BaselineState)
    graph.add_node("decide", nodes.decide)
    graph.add_node("validate_submission", nodes.validate_submission)
    graph.add_edge(START, "decide")
    graph.add_conditional_edges(
        "decide",
        route,
        {"decide": "decide", "validate_submission": "validate_submission"},
    )
    graph.add_conditional_edges(
        "validate_submission", route, {"decide": "decide", "end": END}
    )
    return graph.compile(name="baseline")


class BaselineAgent:
    def __init__(
        self,
        model: Model,
        config: BaselineConfig,
        cancellation_check: Callable[[], bool] | None = None,
    ):
        self.config = config
        self.graph = build_graph(model, config, cancellation_check)

    def run_config(self, request: TurnRequest):
        return {
            "run_name": "baseline_turn",
            "recursion_limit": 2 * self.config.max_model_calls + 10,
            "tags": ["baseline", "lmstudio", self.config.prompt_version],
            "metadata": {
                "game_id": request.game_id,
                "thread_id": request.game_id,
                "ply": request.ply,
                "side": request.side,
                "harness": "baseline",
                "harness_version": self.config.prompt_version,
                "model": self.config.model,
            },
        }

    async def choose_move(self, request: TurnRequest) -> MoveDecision:
        state = await self.graph.ainvoke(
            initial_state(request), config=self.run_config(request)
        )
        decision = state["decision"]
        if decision is None:
            raise HarnessError("Baseline graph ended without a validated move.")
        return MoveDecision(
            move=normalize_move(request.fen, decision["move"]),
            justification=decision["justification"],
        )
