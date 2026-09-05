"""The complete orchestration topology for one move decision."""

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from chess_core import normalize_move
from harness.contracts import HarnessError, MoveDecision, TurnRequest
from harness.model import Model

from .config import AgentConfig
from .nodes import PhaseNodes
from .state import TurnState, initial_state


def route(state: TurnState) -> str:
    return state["next_step"]


def build_graph(
    model: Model,
    config: AgentConfig,
    cancellation_check: Callable[[], bool] | None = None,
):
    nodes = PhaseNodes(model, config, cancellation_check)
    graph = StateGraph(TurnState)
    graph.add_node("defense", nodes.defense)
    graph.add_node("defense_tools", nodes.defense_tools)
    graph.add_node("attack", nodes.attack)
    graph.add_node("attack_tools", nodes.attack_tools)
    graph.add_node("synthesis", nodes.synthesis)
    graph.add_node("synthesis_tools", nodes.synthesis_tools)
    graph.add_edge(START, "defense")
    graph.add_conditional_edges(
        "defense",
        route,
        {
            "defense": "defense",
            "defense_tools": "defense_tools",
            "attack": "attack",
        },
    )
    graph.add_edge("defense_tools", "defense")
    graph.add_conditional_edges(
        "attack",
        route,
        {
            "attack": "attack",
            "attack_tools": "attack_tools",
            "synthesis": "synthesis",
        },
    )
    graph.add_edge("attack_tools", "attack")
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
    return graph.compile(name="agent_player_1")


class AgentPlayer1:
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
            "run_name": "agent_player_1_turn",
            # Each phase can run a model node and a tool node per model pass.
            "recursion_limit": 6 * self.config.max_model_calls + 10,
            "tags": ["agent_player_1", "lmstudio", self.config.prompt_version],
            "metadata": {
                "game_id": request.game_id,
                "thread_id": request.game_id,
                "harness": "agent_player_1",
                "ply": request.ply,
                "side": request.side,
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
            raise HarnessError("Graph ended without a validated move.")
        return MoveDecision(
            move=normalize_move(request.fen, decision["move"]),
            justification=decision["justification"],
            defense_report=state["defense_report"],
            attack_report=state["attack_report"],
        )
