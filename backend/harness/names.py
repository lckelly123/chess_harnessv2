"""Public harness names, with stable version IDs for existing runs and prompts."""

HARNESS_RENAMES = (
    ("agent-player-1-langgraph-v1", "Agent Player 1", "legacy"),
    ("agent-player-2-langgraph-v1", "Agent Player 2", "chess_harness"),
    ("agent-player-3-langgraph-v1", "Agent Player 3", "chess_charness_alt"),
)

HARNESS_NAMES = {harness_id: name for harness_id, _, name in HARNESS_RENAMES}
