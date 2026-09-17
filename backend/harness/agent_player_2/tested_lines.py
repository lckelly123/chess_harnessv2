"""Pure helpers for Agent Player 2's persistent scratch variation tree."""

from __future__ import annotations

import re
from typing import cast

import chess

from .state import TestedLineNode

MAX_SCRATCH_HALFMOVES = 4
BRANCH_ID_PATTERN = re.compile(r"B[1-9]\d*(?:\.[1-9]\d*)*")
PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def copy_nodes(nodes: list[TestedLineNode]) -> list[TestedLineNode]:
    return [cast(TestedLineNode, dict(node)) for node in nodes]


def branch_sort_key(branch_id: str) -> tuple[int, ...]:
    if BRANCH_ID_PATTERN.fullmatch(branch_id) is None:
        raise ValueError(f"Invalid tested-line branch id: {branch_id}")
    return tuple(int(part) for part in branch_id[1:].split("."))


def find_node(
    nodes: list[TestedLineNode], branch_id: str | None
) -> TestedLineNode | None:
    if branch_id is None:
        return None
    return next((node for node in nodes if node["branch_id"] == branch_id), None)


def require_node(nodes: list[TestedLineNode], branch_id: str) -> TestedLineNode:
    node = find_node(nodes, branch_id)
    if node is None:
        raise KeyError(branch_id)
    return node


def child_nodes(
    nodes: list[TestedLineNode], parent_id: str | None
) -> list[TestedLineNode]:
    return sorted(
        (node for node in nodes if node["parent_id"] == parent_id),
        key=lambda node: branch_sort_key(node["branch_id"]),
    )


def lineage(nodes: list[TestedLineNode], branch_id: str | None) -> list[TestedLineNode]:
    if branch_id is None:
        return []
    by_id = {node["branch_id"]: node for node in nodes}
    current = by_id.get(branch_id)
    if current is None:
        raise ValueError(f"Unknown active tested-line branch: {branch_id}")

    path: list[TestedLineNode] = []
    visited: set[str] = set()
    while current is not None:
        current_id = current["branch_id"]
        if current_id in visited:
            raise ValueError("Tested-line tree contains a cycle.")
        visited.add(current_id)
        path.append(current)
        parent_id = current["parent_id"]
        current = by_id.get(parent_id) if parent_id is not None else None
        if parent_id is not None and current is None:
            raise ValueError(f"Tested-line branch {current_id} has no parent.")

    path.reverse()
    if any(node["ply"] != index for index, node in enumerate(path, start=1)):
        raise ValueError("Tested-line branch ply does not match its tree depth.")
    return path


def moves_to_branch(nodes: list[TestedLineNode], branch_id: str | None) -> list[str]:
    return [node["move"] for node in lineage(nodes, branch_id)]


def find_child(
    nodes: list[TestedLineNode], parent_id: str | None, move: str
) -> TestedLineNode | None:
    return next(
        (
            node
            for node in nodes
            if node["parent_id"] == parent_id and node["move"] == move
        ),
        None,
    )


def next_branch_id(nodes: list[TestedLineNode], parent_id: str | None) -> str:
    siblings = child_nodes(nodes, parent_id)
    next_index = (
        max(branch_sort_key(node["branch_id"])[-1] for node in siblings) + 1
        if siblings
        else 1
    )
    return f"B{next_index}" if parent_id is None else f"{parent_id}.{next_index}"


def base_branch(nodes: list[TestedLineNode], branch_id: str) -> TestedLineNode:
    path = lineage(nodes, branch_id)
    if not path:
        raise ValueError(f"Unknown tested-line branch: {branch_id}")
    return path[0]


def base_verification_done(nodes: list[TestedLineNode], branch_id: str) -> bool:
    root = require_node(nodes, branch_id)
    if root["parent_id"] is not None:
        raise ValueError("Verification status is defined only for a base branch.")
    return root["terminal"] or bool(child_nodes(nodes, root["branch_id"]))


def preorder(nodes: list[TestedLineNode]) -> list[TestedLineNode]:
    ordered: list[TestedLineNode] = []

    def visit(parent_id: str | None) -> None:
        for node in child_nodes(nodes, parent_id):
            ordered.append(node)
            visit(node["branch_id"])

    visit(None)
    if len(ordered) != len(nodes):
        raise ValueError("Tested-line tree contains an unreachable branch.")
    return ordered


def material_balance_cp(fen: str, side: str) -> int:
    board = chess.Board(fen)
    color = chess.WHITE if side == "white" else chess.BLACK

    def total(piece_color: chess.Color) -> int:
        return sum(
            len(board.pieces(piece_type, piece_color)) * value
            for piece_type, value in PIECE_VALUES.items()
        )

    return total(color) - total(not color)


def material_change_cp(canonical_fen: str, branch_fen: str, side: str) -> int:
    return material_balance_cp(branch_fen, side) - material_balance_cp(
        canonical_fen, side
    )
