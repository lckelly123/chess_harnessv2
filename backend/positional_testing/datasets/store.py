"""Transactional import and access for the three-table positional library."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .validation import load_collection, load_evaluations

SCHEMA = Path(__file__).with_name("schema.sql")
MIGRATION = Path(__file__).with_name("migrate_three_tables.sql")
PROVENANCE_FIELDS = (
    "source",
    "source_game_id",
    "source_ply",
    "source_url",
    "position_key",
)
CORE_FIELDS = (
    "id",
    "dataset_version",
    "split",
    "phase",
    "position_type",
    "fen",
    "pgn_prefix",
    "last_move_uci",
    "last_move_san",
)
POSITION_FIELDS = (*CORE_FIELDS, *PROVENANCE_FIELDS, "metadata")
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


def ensure_schema(conn) -> None:
    """One transaction, serialized across API/worker/import processes; no version table."""
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':position-schema', 0))"
    )
    legacy = conn.execute(
        "SELECT to_regclass('position_datasets') IS NOT NULL "
        "OR to_regclass('position_run_queues') IS NOT NULL AS present"
    ).fetchone()["present"]
    if legacy:
        conn.execute(MIGRATION.read_text(encoding="utf-8"))
    conn.execute(SCHEMA.read_text(encoding="utf-8"))


def projection(*, summary=False) -> str:
    fields = [field for field in CORE_FIELDS if not summary or field != "pgn_prefix"]
    fields.extend(
        f"(metadata->'provenance'->>'{name}')"
        + ("::integer" if name == "source_ply" else "")
        + f" AS {name}"
        for name in PROVENANCE_FIELDS
        if not summary or name != "position_key"
    )
    # Reference engine answers and manifests never enter browser/model projections.
    fields.append(
        "metadata - 'provenance' - 'dataset' - 'reference_evaluations' AS metadata"
    )
    return ", ".join(fields)


def verify_stored_content(
    conn, rows: list[dict], evaluations: list[dict], version: str
):
    stored = conn.execute(
        f"SELECT {projection()} FROM positions WHERE dataset_version = %s", (version,)
    ).fetchall()
    actual = {str(row["id"]): {**row, "id": str(row["id"])} for row in stored}
    expected = {
        row["id"]: {field: row[field] for field in POSITION_FIELDS} for row in rows
    }
    if actual != expected:
        raise ValueError("Existing dataset content differs from the frozen seed")
    stored_evaluations = conn.execute(
        "SELECT e.value FROM positions p, "
        "jsonb_array_elements(p.metadata->'reference_evaluations') e(value) "
        "WHERE p.dataset_version = %s AND e.value->>'analysis_id' = ANY(%s)",
        (version, sorted({row["analysis_id"] for row in evaluations})),
    ).fetchall()
    actual_evaluations = {
        (row["value"]["position_id"], row["value"]["analysis_id"]): {
            field: row["value"][field] for field in EVALUATION_FIELDS
        }
        for row in stored_evaluations
    }
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
    content_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    dataset = {
        "version": manifest["version"],
        "description": manifest["description"],
        "seed": manifest["seed"],
        "position_count": len(rows),
        "content_sha256": content_hash,
        "manifest": manifest,
        "created_at": datetime.now(UTC).isoformat(),
    }
    references = {}
    for row in evaluations:
        references.setdefault(row["position_id"], []).append(row)
    with connect() as conn:
        ensure_schema(conn)
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", (manifest["version"],)
        )
        existing = conn.execute(
            "SELECT DISTINCT metadata->'dataset'->>'content_sha256' AS content_sha256 "
            "FROM positions WHERE dataset_version = %s",
            (manifest["version"],),
        ).fetchall()
        if existing:
            if {r["content_sha256"] for r in existing} != {content_hash}:
                raise ValueError(
                    "This dataset version is already frozen with different content; create a new version"
                )
            verify_stored_content(conn, rows, evaluations, manifest["version"])
            return {**report, "imported": 0, "status": "already_present"}
        fields = (*CORE_FIELDS, "metadata")
        with conn.cursor() as cursor:
            cursor.executemany(
                f"INSERT INTO positions ({', '.join(fields)}) "
                f"VALUES ({', '.join(['%s'] * len(fields))})",
                [
                    (
                        *[row[name] for name in CORE_FIELDS],
                        Jsonb(
                            {
                                **row["metadata"],
                                "provenance": {
                                    name: row[name] for name in PROVENANCE_FIELDS
                                },
                                "dataset": dataset,
                                "reference_evaluations": references.get(row["id"], []),
                            }
                        ),
                    )
                    for row in rows
                ],
            )
    return {**report, "imported": len(rows), "status": "imported"}


def summary() -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT dataset_version, split, phase, position_type, count(*) AS positions "
            "FROM positions GROUP BY 1,2,3,4 ORDER BY 1,2,3,4"
        ).fetchall()


def list_position_rows() -> list[dict]:
    with connect() as conn:
        return conn.execute(
            f"SELECT {projection(summary=True)} FROM positions "
            "ORDER BY dataset_version DESC, CASE split WHEN 'train' THEN 0 ELSE 1 END, "
            "CASE phase WHEN 'middlegame' THEN 0 WHEN 'opening' THEN 1 ELSE 2 END, "
            "position_type, source_game_id, id"
        ).fetchall()


def get_position_row(position_id: str) -> dict | None:
    with connect() as conn:
        return conn.execute(
            f"SELECT {projection()} FROM positions WHERE id = %s", (position_id,)
        ).fetchone()
