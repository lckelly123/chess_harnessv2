"""Single synthesis-phase chess harness."""

from .config import AgentConfig
from .graph import AgentPlayer3, build_graph

__all__ = ["AgentConfig", "AgentPlayer3", "build_graph"]
