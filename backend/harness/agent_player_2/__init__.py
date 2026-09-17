"""Single synthesis-phase chess harness."""

from .config import AgentConfig
from .graph import AgentPlayer2, build_graph

__all__ = ["AgentConfig", "AgentPlayer2", "build_graph"]
