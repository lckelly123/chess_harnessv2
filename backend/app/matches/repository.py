"""Small SQLite repository for durable match snapshots and replay."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.models import (
    GameFolder,
    GameFolderList,
    GameFolderRef,
    HarnessVersion,
    MatchDetail,
    MatchList,
    MatchSummary,
    PlayerRef,
    PositionRecord,
    TraceEvent,
)
from chess_core import STARTING_FEN, MoveIdentity
from harness.contracts import MoveDecision


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class FolderNameConflictError(ValueError):
    """A case-insensitive folder name is already in use."""


class UnknownFolderError(ValueError):
    """A requested folder does not exist."""


class MatchRepository:
    """Synchronous SQLite operations kept tiny and guarded for API/task access."""

    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._create_schema()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS game_folders (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                white_harness_id TEXT NOT NULL,
                white_name TEXT NOT NULL,
                white_version TEXT NOT NULL,
                black_harness_id TEXT NOT NULL,
                black_name TEXT NOT NULL,
                black_version TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                current_fen TEXT NOT NULL,
                move_count INTEGER NOT NULL DEFAULT 0,
                last_move TEXT,
                current_player TEXT,
                current_phase TEXT,
                termination_reason TEXT,
                folder_id TEXT REFERENCES game_folders(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS positions (
                match_id TEXT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
                ply INTEGER NOT NULL,
                fen TEXT NOT NULL,
                san TEXT NOT NULL,
                player TEXT,
                from_square TEXT,
                to_square TEXT,
                justification TEXT,
                defense_report TEXT,
                attack_report TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (match_id, ply)
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                match_id TEXT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
                timestamp TEXT NOT NULL,
                ply INTEGER NOT NULL,
                player TEXT NOT NULL,
                phase TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT NOT NULL,
                detail TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS matches_started_at
                ON matches(started_at DESC);
            CREATE INDEX IF NOT EXISTS events_match_id
                ON events(match_id, timestamp);
            """
        )
        match_columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(matches)").fetchall()
        }
        if "folder_id" not in match_columns:
            self._connection.execute(
                "ALTER TABLE matches ADD COLUMN folder_id TEXT "
                "REFERENCES game_folders(id) ON DELETE SET NULL"
            )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS matches_folder_id ON matches(folder_id)"
        )
        self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def create_match(
        self,
        match_id: str,
        white: HarnessVersion,
        black: HarnessVersion,
        folder_id: str | None = None,
    ) -> MatchDetail:
        started_at = _now()
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO matches (
                    id, white_harness_id, white_name, white_version,
                    black_harness_id, black_name, black_version,
                    status, started_at, current_fen, current_player, current_phase,
                    folder_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, 'white', 'starting', ?)
                """,
                (
                    match_id,
                    white.id,
                    white.name,
                    white.version,
                    black.id,
                    black.name,
                    black.version,
                    started_at.isoformat(),
                    STARTING_FEN,
                    folder_id,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO positions (
                    match_id, ply, fen, san, created_at
                ) VALUES (?, 0, ?, 'Start', ?)
                """,
                (match_id, STARTING_FEN, started_at.isoformat()),
            )
            self._connection.commit()
        match = self.get_match(match_id)
        assert match is not None
        return match

    def create_folder(self, name: str) -> GameFolder:
        normalized_name = " ".join(name.split())
        if not normalized_name or len(normalized_name) > 60:
            raise ValueError("Folder name must contain 1–60 characters.")
        folder_id = f"folder-{uuid4().hex[:12]}"
        created_at = _now()
        with self._lock:
            try:
                self._connection.execute(
                    "INSERT INTO game_folders (id, name, created_at) VALUES (?, ?, ?)",
                    (folder_id, normalized_name, created_at.isoformat()),
                )
                self._connection.commit()
            except sqlite3.IntegrityError as exc:
                raise FolderNameConflictError(
                    f'A folder named "{normalized_name}" already exists.'
                ) from exc
        return GameFolder(
            id=folder_id,
            name=normalized_name,
            created_at=created_at,
            match_count=0,
        )

    def list_folders(self) -> GameFolderList:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT game_folders.*, COUNT(matches.id) AS match_count
                FROM game_folders
                LEFT JOIN matches ON matches.folder_id = game_folders.id
                GROUP BY game_folders.id
                ORDER BY game_folders.name COLLATE NOCASE, game_folders.created_at
                """
            ).fetchall()
            counts = self._connection.execute(
                """
                SELECT COUNT(*) AS total_matches,
                       SUM(CASE WHEN folder_id IS NULL THEN 1 ELSE 0 END) AS unfiled_count
                FROM matches
                """
            ).fetchone()
        return GameFolderList(
            items=[
                GameFolder(
                    id=row["id"],
                    name=row["name"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    match_count=row["match_count"],
                )
                for row in rows
            ],
            total_matches=counts["total_matches"],
            unfiled_count=counts["unfiled_count"] or 0,
        )

    def folder_exists(self, folder_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM game_folders WHERE id = ?", (folder_id,)
            ).fetchone()
        return row is not None

    def assign_match_folder(
        self, match_id: str, folder_id: str | None
    ) -> MatchDetail | None:
        with self._lock:
            if folder_id is not None:
                folder = self._connection.execute(
                    "SELECT 1 FROM game_folders WHERE id = ?", (folder_id,)
                ).fetchone()
                if folder is None:
                    raise UnknownFolderError(f"Unknown game folder: {folder_id}")
            cursor = self._connection.execute(
                "UPDATE matches SET folder_id = ? WHERE id = ?",
                (folder_id, match_id),
            )
            self._connection.commit()
        if not cursor.rowcount:
            return None
        return self.get_match(match_id)

    def active_count(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS count FROM matches WHERE status IN ('queued', 'running')"
            ).fetchone()
        return int(row["count"])

    def set_turn(self, match_id: str, player: str, ply: int, name: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE matches
                SET current_player = ?, current_phase = 'thinking'
                WHERE id = ? AND status = 'running'
                """,
                (player, match_id),
            )
            if cursor.rowcount:
                self._insert_event(
                    match_id=match_id,
                    ply=ply,
                    player=player,
                    phase="plan",
                    status="active",
                    summary=f"{name} is choosing a move",
                    detail="The selected LangGraph harness is running this turn.",
                )
            self._connection.commit()
            return bool(cursor.rowcount)

    def append_move_if_running(
        self,
        match_id: str,
        *,
        ply: int,
        player: str,
        move: MoveIdentity,
        fen_after: str,
        decision: MoveDecision,
    ) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM matches WHERE id = ?",
                (match_id,),
            ).fetchone()
            if row is None or row["status"] != "running":
                return False
            player_name = row[f"{player}_name"]
            self._connection.execute(
                """
                INSERT INTO positions (
                    match_id, ply, fen, san, player, from_square, to_square,
                    justification, defense_report, attack_report, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    ply,
                    fen_after,
                    move.san,
                    player,
                    move.from_square,
                    move.to_square,
                    decision.justification,
                    decision.defense_report,
                    decision.attack_report,
                    _now().isoformat(),
                ),
            )
            self._connection.execute(
                """
                UPDATE matches
                SET current_fen = ?, move_count = ?, last_move = ?,
                    current_player = ?, current_phase = 'waiting'
                WHERE id = ? AND status = 'running'
                """,
                (
                    fen_after,
                    ply,
                    move.san,
                    "black" if player == "white" else "white",
                    match_id,
                ),
            )
            self._connection.execute(
                """
                UPDATE events SET status = 'complete'
                WHERE match_id = ? AND status = 'active'
                """,
                (match_id,),
            )
            self._insert_event(
                match_id=match_id,
                ply=ply,
                player=player,
                phase="act",
                status="complete",
                summary=f"{player_name} played {move.san}",
                detail=decision.justification,
            )
            self._connection.commit()
            return True

    def complete(self, match_id: str, result: str, reason: str) -> None:
        self._finish(match_id, "completed", result, reason, "complete")

    def stop(self, match_id: str, reason: str) -> None:
        self._finish(match_id, "stopped", "aborted", reason, "complete")

    def fail(self, match_id: str, reason: str) -> None:
        self._finish(match_id, "failed", None, reason, "failed")

    def _finish(
        self,
        match_id: str,
        status: str,
        result: str | None,
        reason: str,
        event_status: str,
    ) -> None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM matches WHERE id = ?", (match_id,)
            ).fetchone()
            if row is None or row["status"] not in {"queued", "running"}:
                return
            player = row["current_player"] or (
                "white" if row["move_count"] % 2 == 0 else "black"
            )
            self._connection.execute(
                """
                UPDATE matches
                SET status = ?, result = ?, ended_at = ?, current_player = NULL,
                    current_phase = NULL, termination_reason = ?
                WHERE id = ?
                """,
                (status, result, _now().isoformat(), reason, match_id),
            )
            self._connection.execute(
                """
                UPDATE events SET status = ?
                WHERE match_id = ? AND status = 'active'
                """,
                (event_status, match_id),
            )
            self._insert_event(
                match_id=match_id,
                ply=row["move_count"],
                player=player,
                phase="verify",
                status=event_status,
                summary=f"Match {status}",
                detail=reason,
            )
            self._connection.commit()

    def recover_interrupted(self) -> None:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id FROM matches WHERE status IN ('queued', 'running')"
            ).fetchall()
        for row in rows:
            self.fail(row["id"], "Backend restarted before the match completed.")

    def get_match(self, match_id: str) -> MatchDetail | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT matches.*,
                       game_folders.id AS folder_ref_id,
                       game_folders.name AS folder_ref_name
                FROM matches
                LEFT JOIN game_folders ON game_folders.id = matches.folder_id
                WHERE matches.id = ?
                """,
                (match_id,),
            ).fetchone()
            if row is None:
                return None
            positions = self._connection.execute(
                "SELECT * FROM positions WHERE match_id = ? ORDER BY ply",
                (match_id,),
            ).fetchall()
            events = self._connection.execute(
                "SELECT * FROM events WHERE match_id = ? ORDER BY timestamp, id",
                (match_id,),
            ).fetchall()
        return MatchDetail(
            **self._summary_values(row),
            positions=[
                PositionRecord(
                    ply=item["ply"],
                    fen=item["fen"],
                    san=item["san"],
                    player=item["player"],
                    from_square=item["from_square"],
                    to_square=item["to_square"],
                )
                for item in positions
            ],
            traces=[
                TraceEvent(
                    id=item["id"],
                    timestamp=datetime.fromisoformat(item["timestamp"]),
                    ply=item["ply"],
                    player=item["player"],
                    phase=item["phase"],
                    status=item["status"],
                    summary=item["summary"],
                    detail=item["detail"],
                )
                for item in events
            ],
        )

    def list_matches(
        self,
        query: str = "",
        *,
        folder_id: str | None = None,
        unfiled_only: bool = False,
    ) -> MatchList:
        needle = query.strip()
        conditions: list[str] = []
        parameters: list[str] = []
        if folder_id is not None:
            conditions.append("matches.folder_id = ?")
            parameters.append(folder_id)
        elif unfiled_only:
            conditions.append("matches.folder_id IS NULL")
        if needle:
            pattern = f"%{needle}%"
            conditions.append(
                """(
                    matches.id LIKE ? COLLATE NOCASE
                    OR matches.white_name LIKE ? COLLATE NOCASE
                    OR matches.white_version LIKE ? COLLATE NOCASE
                    OR matches.black_name LIKE ? COLLATE NOCASE
                    OR matches.black_version LIKE ? COLLATE NOCASE
                    OR matches.status LIKE ? COLLATE NOCASE
                    OR COALESCE(matches.result, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(matches.termination_reason, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(game_folders.name, '') LIKE ? COLLATE NOCASE
                )"""
            )
            parameters.extend([pattern] * 9)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT matches.*,
                       game_folders.id AS folder_ref_id,
                       game_folders.name AS folder_ref_name
                FROM matches
                LEFT JOIN game_folders ON game_folders.id = matches.folder_id
                {where_clause}
                ORDER BY matches.started_at DESC
                """,
                parameters,
            ).fetchall()
        items = [MatchSummary(**self._summary_values(row)) for row in rows]
        return MatchList(items=items, total=len(items))

    def _summary_values(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "white": PlayerRef(
                harness_id=row["white_harness_id"],
                name=row["white_name"],
                version=row["white_version"],
                color="white",
            ),
            "black": PlayerRef(
                harness_id=row["black_harness_id"],
                name=row["black_name"],
                version=row["black_version"],
                color="black",
            ),
            "status": row["status"],
            "result": row["result"],
            "started_at": datetime.fromisoformat(row["started_at"]),
            "ended_at": _parse_datetime(row["ended_at"]),
            "current_fen": row["current_fen"],
            "move_count": row["move_count"],
            "last_move": row["last_move"],
            "current_player": row["current_player"],
            "current_phase": row["current_phase"],
            "termination_reason": row["termination_reason"],
            "folder": (
                GameFolderRef(
                    id=row["folder_ref_id"],
                    name=row["folder_ref_name"],
                )
                if row["folder_ref_id"] is not None
                else None
            ),
        }

    def _insert_event(
        self,
        *,
        match_id: str,
        ply: int,
        player: str,
        phase: str,
        status: str,
        summary: str,
        detail: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO events (
                id, match_id, timestamp, ply, player, phase, status, summary, detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"event-{uuid4().hex}",
                match_id,
                _now().isoformat(),
                ply,
                player,
                phase,
                status,
                summary,
                detail,
            ),
        )
