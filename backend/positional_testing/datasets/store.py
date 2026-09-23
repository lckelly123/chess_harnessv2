"""Transactional import of validated immutable position collections."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .validation import load_collection, load_evaluations

SCHEMA = Path(__file__).with_name("schema.sql")
POSITION_FIELDS = (
    "id",
    "dataset_version",
    "split",
    "phase",
    "position_type",
    "fen",
    "pgn_prefix",
    "last_move_uci",
    "last_move_san",
    "source",
    "source_game_id",
    "source_ply",
    "source_url",
    "position_key",
    "metadata",
)
EVALUATION_FIELDS = (
    "position_id",
    "analysis_id",
    "engine_name",
    "perspective",
    "node_limit",
    "best_move_uci",
    "best_score_cp",
    "best_mate",
    "payload",
)


def verify_stored_content(
    conn, rows: list[dict], evaluations: list[dict], version: str
) -> None:
    stored_rows = conn.execute(
        f"SELECT {', '.join(POSITION_FIELDS)} FROM positions WHERE dataset_version = %s",
        (version,),
    ).fetchall()
    actual_positions = {}
    for row in stored_rows:
        row["id"] = str(row["id"])
        actual_positions[row["id"]] = row
    expected_positions = {
        row["id"]: {field: row[field] for field in POSITION_FIELDS} for row in rows
    }
    if actual_positions != expected_positions:
        raise ValueError("Existing dataset content differs from the frozen seed")
    stored_evaluations = conn.execute(
        f"SELECT {', '.join('e.' + field for field in EVALUATION_FIELDS)} "
        "FROM position_evaluations e JOIN positions p ON p.id = e.position_id "
        "WHERE p.dataset_version = %s AND e.analysis_id = ANY(%s)",
        (version, sorted({row["analysis_id"] for row in evaluations})),
    ).fetchall()
    actual_evaluations = {}
    for row in stored_evaluations:
        row["position_id"] = str(row["position_id"])
        actual_evaluations[(row["position_id"], row["analysis_id"])] = row
    expected_evaluations = {
        (row["position_id"], row["analysis_id"]): {
            field: row[field] for field in EVALUATION_FIELDS
        }
        for row in evaluations
    }
    if actual_evaluations != expected_evaluations:
        raise ValueError("Existing curation evaluations differ from the frozen seed")


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("POSITIONS_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("POSITIONS_DB_PORT", "5433")),
        dbname=os.getenv("POSITIONS_DB_NAME", "chess_positions"),
        user=os.getenv("POSITIONS_DB_USER", "chess"),
        password=os.getenv("POSITIONS_DB_PASSWORD", "chess_local"),
        connect_timeout=10,
        row_factory=dict_row,
    )


def import_collection(directory: Path) -> dict:
    rows, manifest, report = load_collection(directory)
    evaluations = load_evaluations(directory, manifest, rows)
    # Covers positions, references and curation policy; never silently changes v1.
    content_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with connect() as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", (manifest["version"],)
        )
        existing = conn.execute(
            "SELECT content_sha256 FROM position_datasets WHERE version = %s",
            (manifest["version"],),
        ).fetchone()
        if existing:
            if existing["content_sha256"] != content_hash:
                raise ValueError(
                    "This dataset version is already frozen with different content; create a new version"
                )
            verify_stored_content(conn, rows, evaluations, manifest["version"])
            return {**report, "imported": 0, "status": "already_present"}
        conn.execute(
            "INSERT INTO position_datasets (version, description, seed, position_count, content_sha256, manifest) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                manifest["version"],
                manifest["description"],
                manifest["seed"],
                len(rows),
                content_hash,
                Jsonb(manifest),
            ),
        )
        fields = POSITION_FIELDS
        with conn.cursor() as cursor:
            cursor.executemany(
                f"INSERT INTO positions ({', '.join(fields)}) VALUES ({', '.join(['%s'] * len(fields))})",
                [
                    tuple(
                        Jsonb(row[name]) if name == "metadata" else row[name]
                        for name in fields
                    )
                    for row in rows
                ],
            )
            fields = EVALUATION_FIELDS
            cursor.executemany(
                f"INSERT INTO position_evaluations ({', '.join(fields)}) VALUES ({', '.join(['%s'] * len(fields))})",
                [
                    tuple(
                        Jsonb(row[name]) if name == "payload" else row[name]
                        for name in fields
                    )
                    for row in evaluations
                ],
            )
    return {**report, "imported": len(rows), "status": "imported"}


def summary() -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT dataset_version, split, phase, position_type, count(*) AS positions FROM positions GROUP BY 1,2,3,4 ORDER BY 1,2,3,4"
        ).fetchall()


def list_position_rows() -> list[dict]:
    """Small-library browser projection: no histories or reference evaluations."""
    fields = [
        field
        for field in POSITION_FIELDS
        if field not in {"pgn_prefix", "position_key"}
    ]
    with connect() as conn:
        return conn.execute(
            f"SELECT {', '.join(fields)} FROM positions "
            "ORDER BY dataset_version DESC, CASE split WHEN 'train' THEN 0 ELSE 1 END, "
            "CASE phase WHEN 'middlegame' THEN 0 WHEN 'opening' THEN 1 ELSE 2 END, "
            "position_type, source_game_id, id"
        ).fetchall()


def get_position_row(position_id: str) -> dict | None:
    with connect() as conn:
        return conn.execute(
            f"SELECT {', '.join(POSITION_FIELDS)} FROM positions WHERE id = %s",
            (position_id,),
        ).fetchone()
