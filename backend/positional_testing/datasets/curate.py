"""Build a reproducible 400-position pilot from public Lichess data and Stockfish.

Network/engine work happens only when this explicit CLI is invoked. Raw downloads
and resumable screening results live in the ignored backend/data directory.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from .validation import (
    PHASE_RULE,
    QUOTAS,
    clean_prefix,
    phase_of,
    position_key,
    validate_collection,
    validate_position,
)

GAME_DATASET = "Lichess/standard-chess-games"
PUZZLE_DATASET = "Lichess/chess-puzzles"
SCREEN_NODES = 80_000
REFERENCE_NODES = 500_000
POLICY = "quiet-screen-v1"
VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
}


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class Downloads:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.urls: list[str] = []

    def get(self, url: str) -> bytes:
        self.urls.append(url)
        path = self.directory / (digest(url.encode()) + ".cache")
        if path.exists():
            return path.read_bytes()
        for attempt in range(5):
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": "ChessHarness-position-curation/1.0"}
                )
                with urllib.request.urlopen(request, timeout=45) as response:
                    payload = response.read()
                path.write_bytes(payload)
                return payload
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 4:
                    raise
                delay = min(
                    30, int(exc.headers.get("Retry-After", "5")) * (attempt + 1)
                )
                print(f"Public source HTTP {exc.code}; retry in {delay}s", flush=True)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError):
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
        raise RuntimeError("Download retries exhausted")

    def json(self, url: str) -> dict:
        return json.loads(self.get(url))

    def rows(self, dataset: str, offset: int, length: int = 100) -> dict:
        query = urllib.parse.urlencode(
            {
                "dataset": dataset,
                "config": "default",
                "split": "train",
                "offset": offset,
                "length": length,
            }
        )
        return self.json("https://datasets-server.huggingface.co/rows?" + query)


def material(board: chess.Board, color: chess.Color) -> int:
    return sum(
        weight * (len(board.pieces(piece, color)) - len(board.pieces(piece, not color)))
        for piece, weight in VALUES.items()
    )


class Analyst:
    def __init__(self, executable: str, directory: Path):
        self.engine = chess.engine.SimpleEngine.popen_uci(executable, timeout=120)
        self.engine.configure({"Threads": 1, "Hash": 128})
        self.name = self.engine.id.get("name", "Stockfish")
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def analyse(self, board: chess.Board, nodes: int) -> dict:
        cache_key = digest(
            (
                clean_prefix(board)
                + self.name
                + str(nodes)
                + "multipv3-threads1-hash128-complete-depth-v1"
            ).encode()
        )
        path = self.directory / (cache_key + ".json")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        self.engine.configure({"Clear Hash": None})
        with self.engine.analysis(
            board, chess.engine.Limit(nodes=nodes), multipv=3, game=object()
        ) as stream:
            variations = complete_variations(stream, min(3, board.legal_moves.count()))
        pvs = []
        for info in variations:
            if (
                "pv" not in info
                or "score" not in info
                or info.get("lowerbound")
                or info.get("upperbound")
            ):
                continue
            score = info["score"].pov(board.turn)
            cursor = board.copy()
            sans, ucis = [], []
            for move in info["pv"]:
                if move not in cursor.legal_moves:
                    raise ValueError("Engine returned an illegal PV")
                sans.append(cursor.san(move))
                ucis.append(move.uci())
                cursor.push(move)
            sample = board.copy()
            for move in info["pv"][:10]:
                sample.push(move)
            root = info["pv"][0]
            pvs.append(
                {
                    "move_uci": root.uci(),
                    "score_cp": score.score(),
                    "mate": score.mate(),
                    "moves_uci": ucis,
                    "moves_san": sans,
                    "depth": info.get("depth"),
                    "nodes": info.get("nodes"),
                    "forcing_first_move": board.is_capture(root)
                    or board.gives_check(root)
                    or bool(root.promotion),
                    "material_delta_after_10_plies_cp": material(sample, board.turn)
                    - material(board, board.turn),
                }
            )
        result = {
            "engine": self.name,
            "node_limit": nodes,
            "multipv": 3,
            "threads": 1,
            "hash_mb": 128,
            "perspective": "side_to_move",
            "pvs": pvs,
        }
        path.write_text(json.dumps(result), encoding="utf-8")
        return result

    def close(self) -> None:
        self.engine.quit()


def complete_variations(stream, count: int) -> list[dict]:
    """Keep the last complete depth, before an interrupted next-depth search.

    Streaming info avoids stale bound flags in python-chess's merged InfoDicts.
    Requiring a complete depth also avoids comparing candidates at mixed depths.
    """
    depths: dict[int, dict[int, dict]] = {}
    for info in stream:
        if (
            not info.get("pv")
            or "score" not in info
            or info.get("lowerbound")
            or info.get("upperbound")
        ):
            continue
        depths.setdefault(info["depth"], {})[info.get("multipv", 1)] = info
    for depth in sorted(depths, reverse=True):
        lines = depths[depth]
        if set(lines) == set(range(1, count + 1)):
            ordered = [lines[index] for index in range(1, count + 1)]
            if len({line["pv"][0] for line in ordered}) == count:
                return ordered
    return []


def quiet_rejection(analysis: dict) -> str | None:
    lines = analysis["pvs"]
    if len(lines) < 3 or any(pv["mate"] is not None for pv in lines):
        return "mate_or_incomplete_analysis"
    best = lines[0]
    if abs(best["score_cp"]) > 180:
        return "large_existing_advantage"
    if best["forcing_first_move"]:
        return "forcing_best_move"
    if sum(not pv["forcing_first_move"] for pv in lines) < 2:
        return "insufficient_quiet_candidates"
    if best["score_cp"] - lines[1]["score_cp"] > 100:
        return "single_move_dependency"
    if len(best["moves_uci"]) < 8:
        return "short_principal_variation"
    if abs(best["material_delta_after_10_plies_cp"]) > 100:
        return "short_term_material_swing"
    return None


def parse_game(pgn: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None or game.errors or game.board().fen() != chess.STARTING_FEN:
        raise ValueError("Invalid or nonstandard source game")
    return game


def source_id(value: str) -> str:
    match = re.search(r"(?:lichess\.org/)?([A-Za-z0-9]{8})(?:[/#]|$)", value)
    if not match:
        raise ValueError("No source game ID")
    return match.group(1)


def make_row(
    board: chess.Board, game_id: str, kind: str, version: str, metadata: dict
) -> dict:
    previous = board.copy()
    last = previous.pop()
    return {
        "id": str(
            uuid.uuid5(
                uuid.NAMESPACE_URL, f"chess-harness/{version}/{game_id}/{board.ply()}"
            )
        ),
        "dataset_version": version,
        "split": "train",
        "phase": phase_of(board),
        "position_type": kind,
        "fen": board.fen(),
        "pgn_prefix": clean_prefix(board),
        "last_move_uci": last.uci(),
        "last_move_san": previous.san(last),
        "source": "lichess_puzzle" if kind == "tactical" else "lichess_game",
        "source_game_id": game_id,
        "source_ply": board.ply(),
        "source_url": f"https://lichess.org/{game_id}#{board.ply()}",
        "position_key": position_key(board),
        "metadata": {"license": "CC0-1.0", "phase_rule": PHASE_RULE, **metadata},
    }


class Curator:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.cache = args.cache / args.version
        self.cache.mkdir(parents=True, exist_ok=True)
        self.downloads = Downloads(self.cache / "http")
        self.analyst = Analyst(args.engine, self.cache / "analysis")
        checkpoint = self.cache / "selected.jsonl"
        self.selected = (
            [
                json.loads(line)
                for line in checkpoint.read_text(encoding="utf-8").splitlines()
            ]
            if checkpoint.exists()
            else []
        )
        self.counts = Counter()
        self.games, self.boards = set(), set()
        progress_path = self.cache / "progress.json"
        progress = (
            json.loads(progress_path.read_text()) if progress_path.exists() else {}
        )
        self.rejections = Counter(progress.get("rejections", {}))
        self.pages = progress.get("pages", {"quiet": [], "tactical": []})
        self.cursors = progress.get("cursors", {})
        for item in self.selected:
            self.track(item["position"])

    def checkpoint_progress(self) -> None:
        path = self.cache / "progress.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "rejections": dict(self.rejections),
                    "pages": self.pages,
                    "cursors": self.cursors,
                }
            ),
            encoding="utf-8",
        )
        # Windows file indexers can briefly hold the checkpoint during replacement.
        for attempt in range(8):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.1 * (attempt + 1))

    def track(self, row: dict) -> None:
        self.counts[
            (row["phase"], row["position_type"], chess.Board(row["fen"]).turn)
        ] += 1
        self.games.add(row["source_game_id"])
        self.boards.add(row["position_key"])

    def needed(self, board: chess.Board, kind: str) -> bool:
        phase = phase_of(board)
        return (
            phase is not None
            and self.counts[(phase, kind, board.turn)] < QUOTAS[(phase, kind)]
        )

    def complete(self, kind: str) -> bool:
        return all(
            self.counts[(phase, kind, color)] == count
            for (phase, position_type), count in QUOTAS.items()
            if position_type == kind
            for color in chess.COLORS
        )

    def accept(self, row: dict, analysis: dict, screen: dict) -> None:
        validate_position(row)
        best = analysis["pvs"][0]
        evaluation = {
            "position_id": row["id"],
            "analysis_id": "stockfish18-curation-v1",
            "engine_name": self.analyst.name,
            "perspective": "side_to_move",
            "node_limit": REFERENCE_NODES,
            "best_move_uci": best["move_uci"],
            "best_score_cp": best["score_cp"],
            "best_mate": best["mate"],
            "payload": {**analysis, "screening": screen},
        }
        item = {"position": row, "evaluation": evaluation}
        with (self.cache / "selected.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
        self.selected.append(item)
        self.track(row)
        if len(self.selected) % 10 == 0:
            print(
                json.dumps(
                    {
                        "accepted": len(self.selected),
                        "buckets": {
                            f"{p}/{t}/{('white' if c else 'black')}": n
                            for (p, t, c), n in sorted(self.counts.items())
                        },
                    }
                ),
                flush=True,
            )

    def puzzle(self, puzzle: dict) -> None:
        if not (
            1000 <= puzzle["Rating"] <= 2400
            and puzzle["RatingDeviation"] <= 100
            and puzzle["Popularity"] >= 70
            and puzzle["NbPlays"] >= 100
        ):
            return
        before = chess.Board(puzzle["FEN"])
        moves = [chess.Move.from_uci(move) for move in puzzle["Moves"].split()]
        if len(moves) < 2 or moves[0] not in before.legal_moves:
            return
        target = before.copy()
        target.push(moves[0])
        phase = phase_of(target)
        if not self.needed(target, "tactical") or phase not in puzzle["Themes"]:
            return
        game_id = source_id(puzzle["GameId"])
        if game_id in self.games or position_key(target) in self.boards:
            return
        # Keep each tactical phase from becoming a collection of mating puzzles.
        existing_mates = sum(
            "mate" in x["position"]["metadata"].get("themes", [])
            for x in self.selected
            if x["position"]["phase"] == phase
            and x["position"]["position_type"] == "tactical"
        )
        if "mate" in puzzle["Themes"] and existing_mates >= QUOTAS[(phase, "tactical")]:
            return
        pgn = self.downloads.get(
            f"https://lichess.org/game/export/{game_id}?clocks=false&evals=false&opening=false"
        ).decode()
        game = parse_game(pgn)
        board = game.board()
        found = False
        for move in game.mainline_moves():
            matches = board.fen() == before.fen() and move == moves[0]
            if move not in board.legal_moves:
                raise ValueError("Illegal source game")
            board.push(move)
            if matches:
                found = True
                break
        if not found or board.is_game_over(claim_draw=True):
            self.rejections["puzzle_history_mismatch_or_terminal"] += 1
            return
        solution = board.copy()
        for move in moves[1:]:
            if move not in solution.legal_moves:
                self.rejections["invalid_puzzle_solution"] += 1
                return
            solution.push(move)
        analysis = self.analyst.analyse(board, REFERENCE_NODES)
        if not analysis["pvs"] or analysis["pvs"][0]["move_uci"] != moves[1].uci():
            self.rejections["puzzle_engine_disagrees"] += 1
            return
        metadata = {
            "puzzle_id": puzzle["PuzzleId"],
            "puzzle_rating": puzzle["Rating"],
            "puzzle_rating_deviation": puzzle["RatingDeviation"],
            "puzzle_popularity": puzzle["Popularity"],
            "puzzle_plays": puzzle["NbPlays"],
            "themes": puzzle["Themes"],
            "opening_tags": puzzle["OpeningTags"] or [],
            "curation_status": "source_puzzle_and_engine_verified",
        }
        self.accept(
            make_row(board, game_id, "tactical", self.args.version, metadata),
            analysis,
            {
                "source_solution_first_move": moves[1].uci(),
                "source_solution_legal": True,
                "source_setup_move_applied": True,
            },
        )

    def quiet_game(self, source: dict) -> None:
        if min(source.get("WhiteElo") or 0, source.get("BlackElo") or 0) < 1600:
            return
        time_control = str(source.get("TimeControl", ""))
        try:
            initial, increment = map(int, time_control.split("+"))
        except ValueError:
            return
        if initial + 40 * increment < 600:
            return
        game_id = source_id(source["Site"])
        if game_id in self.games:
            return
        game = parse_game(source["movetext"])
        board, candidates = game.board(), []
        for move in game.mainline_moves():
            if move not in board.legal_moves:
                raise ValueError("Illegal source game")
            board.push(move)
            if board.fullmove_number < 6 or not self.needed(board, "quiet"):
                continue
            if (
                board.is_check()
                or len(board.piece_map()) < 8
                or board.legal_moves.count() < 6
                or abs(material(board, board.turn)) > 300
            ):
                continue
            if (
                board.is_game_over(claim_draw=True)
                or position_key(board) in self.boards
            ):
                continue
            candidates.append(board.copy())
        random.Random(f"{self.args.seed}/{game_id}/positions").shuffle(candidates)
        # Sample across phases: a lost endgame should not hide a useful middlegame.
        buckets = {
            phase: [board for board in candidates if phase_of(board) == phase]
            for phase in ("endgame", "middlegame", "opening")
        }
        candidates = [
            boards[index]
            for index in range(6)
            for boards in buckets.values()
            if index < len(boards)
        ]
        for board in candidates[:6]:
            quick = self.analyst.analyse(board, SCREEN_NODES)
            reason = quiet_rejection(quick)
            if reason:
                self.rejections[reason] += 1
                continue
            reference = self.analyst.analyse(board, REFERENCE_NODES)
            reason = quiet_rejection(reference)
            if (
                not reason
                and abs(reference["pvs"][0]["score_cp"] - quick["pvs"][0]["score_cp"])
                > 40
            ):
                reason = "unstable_evaluation"
            if reason:
                self.rejections[reason] += 1
                continue
            metadata = {
                "source_white_rating": source["WhiteElo"],
                "source_black_rating": source["BlackElo"],
                "source_time_control": time_control,
                "source_date": source.get("UTCDate"),
                "opening": source.get("Opening"),
                "eco": source.get("ECO"),
                "curation_policy": POLICY,
                "curation_status": "engine_screened",
                "difficulty_rating": None,
            }
            self.accept(
                make_row(board, game_id, "quiet", self.args.version, metadata),
                reference,
                {
                    "policy": POLICY,
                    "quick_node_limit": SCREEN_NODES,
                    "quick_best_cp": quick["pvs"][0]["score_cp"],
                    "rejection": None,
                },
            )
            return

    def gather(self, kind: str, dataset: str) -> None:
        if self.complete(kind):
            return
        initial = self.downloads.rows(dataset, 0, 1)
        total = initial["num_rows_total"]
        # Reproduce the same page order after resuming, independently of candidate RNG.
        page_rng = random.Random(f"{self.args.seed}/{kind}/pages")
        resume_page, resume_row = self.cursors.get(kind, [0, 0])
        for number in range(self.args.max_pages):
            if self.complete(kind):
                break
            offset = page_rng.randrange(max(1, total // 100 - 1)) * 100
            if number < resume_page:
                continue
            if len(self.pages[kind]) <= number:
                self.pages[kind].append(offset)
            try:
                page = self.downloads.rows(dataset, offset)
            except (urllib.error.URLError, TimeoutError) as exc:
                print(
                    f"Skipped unavailable public page {offset}: {type(exc).__name__}",
                    flush=True,
                )
                self.rejections["source_page_unavailable"] += 1
                self.cursors[kind] = [number + 1, 0]
                self.checkpoint_progress()
                continue
            candidates = [item["row"] for item in page["rows"]]
            random.Random(f"{self.args.seed}/{kind}/{offset}").shuffle(candidates)
            for index, row in enumerate(candidates):
                if number == resume_page and index < resume_row:
                    continue
                if self.complete(kind):
                    break
                try:
                    if kind == "tactical":
                        self.puzzle(row)
                    else:
                        self.quiet_game(row)
                except (ValueError, KeyError, urllib.error.URLError) as exc:
                    self.rejections[type(exc).__name__] += 1
                    if self.rejections[type(exc).__name__] <= 3:
                        print(f"Rejected source record: {exc}", flush=True)
                self.cursors[kind] = [number, index + 1]
                self.checkpoint_progress()
            self.cursors[kind] = [number + 1, 0]
            self.checkpoint_progress()
            if number % 5 == 0:
                print(
                    f"{kind}: pages={number + 1}, accepted={len(self.selected)}",
                    flush=True,
                )
        if not self.complete(kind):
            raise RuntimeError(
                f"Candidate budget exhausted before {kind} quotas were filled; checkpoint retained"
            )

    def save(self) -> dict:
        split_rng = random.Random(self.args.seed)
        rows, evaluations = [], []
        for phase, kind in QUOTAS:
            for color in chess.COLORS:
                items = sorted(
                    (
                        item
                        for item in self.selected
                        if item["position"]["phase"] == phase
                        and item["position"]["position_type"] == kind
                        and chess.Board(item["position"]["fen"]).turn == color
                    ),
                    key=lambda x: x["position"]["id"],
                )
                split_rng.shuffle(items)
                for index, item in enumerate(items):
                    row = {
                        **item["position"],
                        "split": "train" if index < len(items) // 2 else "test",
                    }
                    rows.append(row)
                    evaluations.append(item["evaluation"])
        report = validate_collection(rows, self.args.version)
        output = self.args.output / self.args.version
        output.mkdir(parents=True, exist_ok=True)
        if (output / "manifest.json").exists():
            raise ValueError(
                "Output dataset is already frozen; use a new version or the existing importer"
            )
        position_bytes = (
            "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"
        ).encode()
        evaluation_bytes = (
            "\n".join(json.dumps(row, sort_keys=True) for row in evaluations) + "\n"
        ).encode()
        sources = []
        for dataset in (GAME_DATASET, PUZZLE_DATASET):
            info = self.downloads.json("https://huggingface.co/api/datasets/" + dataset)
            sources.append(
                {
                    "dataset": dataset,
                    "url": "https://huggingface.co/datasets/" + dataset,
                    "observed_revision": info.get("sha"),
                    "license": "CC0-1.0",
                }
            )
        manifest = {
            "version": self.args.version,
            "description": "400-position pilot: 200 train / 200 test; 60% middlegame, 20% opening, 20% endgame; 80% quiet, 20% tactical",
            "seed": self.args.seed,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "position_count": len(rows),
            "positions_sha256": digest(position_bytes),
            "evaluations_sha256": digest(evaluation_bytes),
            "sources": sources,
            "phase_rule": PHASE_RULE,
            "curation_policy": POLICY,
            "engine": self.analyst.name,
            "engine_binary_sha256": digest(Path(self.args.engine).read_bytes()),
            "reference_nodes": REFERENCE_NODES,
            "screen_nodes": SCREEN_NODES,
            "sampling": "seeded random 100-row pages from public dataset snapshots; one selected position per source game; shuffled within phase/type/side before equal split",
            "quiet_filters": {
                "min_source_rating_each": 1600,
                "min_estimated_seconds": 600,
                "min_fullmove": 6,
                "min_pieces": 8,
                "min_legal_moves": 6,
                "max_initial_material_imbalance_cp": 300,
                "in_check": False,
                "abs_best_cp_max": 180,
                "best_second_gap_cp_max": 100,
                "stable_score_difference_cp_max": 40,
                "min_nonforcing_moves_in_top3": 2,
                "best_move_nonforcing": True,
                "abs_material_delta_after_10_plies_cp_max": 100,
            },
            "quiet_label_limit": "Engine-screened operational definition, not proof that all hidden tactics are absent; no human positional-difficulty rating assigned.",
            "puzzle_filters": {
                "rating_min": 1000,
                "rating_max": 2400,
                "rating_deviation_max": 100,
                "popularity_min": 70,
                "plays_min": 100,
                "engine_best_agrees_with_solution": True,
                "max_mate_theme_fraction_per_phase": 0.5,
            },
            "pages": self.pages,
            "rejections": dict(self.rejections),
            "validation": report,
        }
        (output / "positions.jsonl").write_bytes(position_bytes)
        (output / "evaluations.jsonl").write_bytes(evaluation_bytes)
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--seed", type=int, default=20260922)
    parser.add_argument("--cache", type=Path, default=Path("data/position_curation"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("seed"))
    parser.add_argument("--max-pages", type=int, default=2000)
    args = parser.parse_args()
    curator = Curator(args)
    try:
        curator.gather("tactical", PUZZLE_DATASET)
        curator.gather("quiet", GAME_DATASET)
        print(json.dumps(curator.save(), indent=2), flush=True)
    finally:
        curator.analyst.close()


if __name__ == "__main__":
    main()
