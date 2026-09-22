"""Single-phase orchestration for one move decision."""

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from chess_core import normalize_move
from harness.contracts import HarnessError, MoveDecision, TurnInput, TurnRequest
from harness.model import Model

from .config import AgentConfig
from .nodes import SynthesisNodes
from .state import TurnState, initial_state, prepare_turn


def route(state: TurnState) -> str:
    return state["next_step"]


def build_graph(
    model: Model,
    config: AgentConfig,
    cancellation_check: Callable[[], bool] | None = None,
    *,
    accept_turn_input: bool = False,
):
    nodes = SynthesisNodes(model, config, cancellation_check)
    graph = (
        StateGraph(TurnState, input_schema=TurnInput)
        if accept_turn_input
        else StateGraph(TurnState)
    )
    if accept_turn_input:
        graph.add_node("prepare_turn", prepare_turn)
    graph.add_node("synthesis", nodes.synthesis)
    graph.add_node("synthesis_tools", nodes.synthesis_tools)
    if accept_turn_input:
        graph.add_edge(START, "prepare_turn")
        graph.add_edge("prepare_turn", "synthesis")
    else:
        graph.add_edge(START, "synthesis")
    graph.add_conditional_edges(
        "synthesis",
        route,
        {
            "synthesis": "synthesis",
            "synthesis_tools": "synthesis_tools",
            "end": END,
        },
    )
    graph.add_edge("synthesis_tools", "synthesis")
    return graph.compile(name="agent_player3")


class AgentPlayer3:
    """Small caller-facing adapter; graph state is fresh for every invocation."""

    def __init__(
        self,
        model: Model,
        config: AgentConfig,
        cancellation_check: Callable[[], bool] | None = None,
    ):
        self.config = config
        self.graph = build_graph(model, config, cancellation_check)

    def run_config(self, request: TurnRequest):
        return {
            "run_name": "agent_player3_turn",
            # A model pass can route through one tool node before repeating.
            "recursion_limit": 2 * self.config.max_model_calls + 4,
            "tags": [
                "agent_player3",
                self.config.provider,
                self.config.prompt_version,
            ],
            "metadata": {
                "game_id": request.game_id,
                "thread_id": request.game_id,
                "harness": "agent_player3",
                "ply": request.ply,
                "side": request.side,
                "harness_version": self.config.prompt_version,
                "model": self.config.model,
                "provider": self.config.provider,
            },
        }

    async def choose_move(self, request: TurnRequest) -> MoveDecision:
        state = await self.graph.ainvoke(
            initial_state(request), config=self.run_config(request)
        )
        decision = state["decision"]
        if decision is None:
            raise HarnessError("Graph ended without a validated move.")
        return MoveDecision(
            move=normalize_move(request.fen, decision["move"]),
            justification=decision["justification"],
        )
