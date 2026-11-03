"""Human-readable summaries and append-only, token-exact trajectory records."""

import json
import math
import os
import re
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

TERMINAL = {"completed", "failed", "stopped", "interrupted"}
TOOLS = (
    "scratch_play_move",
    "scratch_undo",
    "scratch_reset",
    "inspect_square",
    "annotate_branch",
    "submit_move",
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def valid_name(value):
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10))
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value)
        or value.endswith(".")
        or value.split(".")[0].upper() in reserved
    ):
        raise ValueError(
            "Use 1–80 letters, numbers, dots, hyphens or underscores for the run name."
        )
    return value


def timestamp():
    return datetime.now(UTC).isoformat()


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def validate_capture(capture):
    """Never silently publish text-only or misaligned output as trainable data."""
    if not isinstance(capture, dict):
        raise ValueError("The capture worker did not return token data.")
    for key in ("prompt_token_ids", "completion_token_ids"):
        values = capture.get(key)
        if not isinstance(values, list) or any(
            type(v) is not int or v < 0 for v in values
        ):
            raise ValueError(f"Invalid {key} from the capture worker.")
    count = len(capture["completion_token_ids"])
    for key in ("old_logprobs", "sampling_logprobs"):
        values = capture.get(key)
        if (
            not isinstance(values, list)
            or len(values) != count
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or v > 1e-5
                for v in values
            )
        ):
            raise ValueError(f"Invalid or misaligned {key} from the capture worker.")
    if not all(
        isinstance(capture.get(key), str)
        for key in ("input", "generated_response", "finish_reason")
    ):
        raise ValueError("The capture worker omitted required response metadata.")


class CollectionStore:
    def __init__(self, root=None):
        self.root = Path(
            root
            or os.getenv("GRPO_OUTPUT_ROOT")
            or PROJECT_ROOT / "models/training_data/RL_testing"
        ).resolve()
        self._lock = threading.RLock()

    def path(self, name):
        path = self.root / valid_name(name)
        if path.resolve().parent != self.root:
            raise ValueError("Collection path must stay inside RL_testing.")
        return path

    def create(
        self, name, position_id, harness_id, model_name, *, seed, position, harness
    ):
        with self._lock:
            path = self.path(name)
            self.root.mkdir(parents=True, exist_ok=True)
            path.mkdir()  # Exclusive: an existing collection is never overwritten.
            manifest = {
                "position_id": position_id,
                "qlora_adapter_version": model_name,
                "trajectories": [
                    {
                        "trajectory": i,
                        "status": "pending",
                        "cp_loss": None,
                        "rejected_model_calls": 0,
                        "tool_counts": dict.fromkeys(TOOLS, 0),
                    }
                    for i in range(1, 11)
                ],
            }
            state = {
                "name": name,
                "status": "preparing",
                "positionId": position_id,
                "harnessId": harness_id,
                "modelName": model_name,
                "currentTrajectory": None,
                "currentCall": 0,
                "stopping": False,
                "outputDirectory": f"models/training_data/RL_testing/{name}",
                "error": None,
                "createdAt": timestamp(),
                "updatedAt": timestamp(),
            }
            config = {
                "schema_version": 1,
                "position": position,
                "harness": harness,
                "group_seed": seed,
                "seed_rule": "group_seed + trajectory_index * 100000 + call_index",
                "failure_policy": "ten attempts, including failures; no replacements",
                "tool_count_policy": "all model-requested tools, including rejected calls",
                "loss_mask_policy": "all newly generated tokens; construct padding masks at training time",
                "collection": state,
            }
            atomic_json(path / "manifest.json", manifest)
            atomic_json(path / "capture_config.json", config)
            for i in range(1, 11):
                (path / f"trajectory_{i:02d}.jsonl").touch(exist_ok=False)
            return self.get(name)

    def _read(self, name):
        path = self.path(name)
        return (
            path,
            json.loads((path / "manifest.json").read_text(encoding="utf-8")),
            json.loads((path / "capture_config.json").read_text(encoding="utf-8")),
        )

    def get(self, name):
        with self._lock:
            _, manifest, config = self._read(name)
            state = deepcopy(config["collection"])
            state["trajectories"] = [
                {
                    "trajectory": t["trajectory"],
                    "status": t["status"],
                    "cpLoss": t["cp_loss"],
                    "rejectedModelCalls": t["rejected_model_calls"],
                    "toolCounts": t["tool_counts"],
                }
                for t in manifest["trajectories"]
            ]
            state["totalTrajectories"] = 10
            state["completedTrajectories"] = sum(
                t["status"] in TERMINAL for t in manifest["trajectories"]
            )
            return state

    def update(
        self,
        name,
        *,
        trajectory=None,
        trajectory_status=None,
        cp_loss=None,
        metadata=None,
        **state,
    ):
        with self._lock:
            path, manifest, config = self._read(name)
            if trajectory is not None:
                item = manifest["trajectories"][trajectory - 1]
                if trajectory_status is not None:
                    item["status"] = trajectory_status
                item["cp_loss"] = cp_loss
            if metadata is not None:
                config["capture_worker"] = metadata
            config["collection"].update(state, updatedAt=timestamp())
            atomic_json(path / "manifest.json", manifest)
            atomic_json(path / "capture_config.json", config)

    def append_call(self, name, trajectory, record):
        with self._lock:
            path, manifest, config = self._read(name)
            output = path / f"trajectory_{trajectory:02d}.jsonl"
            records = self.read_calls(output, allow_incomplete_tail=False)
            if not any(r["call_index"] == record["call_index"] for r in records):
                with output.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(
                        json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                records.append(record)
            self.recount(manifest["trajectories"][trajectory - 1], records)
            config["collection"].update(
                currentCall=record["call_index"], updatedAt=timestamp()
            )
            atomic_json(path / "manifest.json", manifest)
            atomic_json(path / "capture_config.json", config)

    @staticmethod
    def read_calls(path, *, allow_incomplete_tail=True):
        records = []
        if not path.exists():
            return records
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                if not allow_incomplete_tail or index != len(lines) - 1:
                    raise ValueError(
                        "A trajectory has a corrupt JSONL record."
                    ) from None
                # A crash can leave the final write incomplete. Preserve it on disk.
        return records

    @staticmethod
    def recount(item, records):
        item["rejected_model_calls"] = 0
        item["tool_counts"] = dict.fromkeys(TOOLS, 0)
        seen = set()
        for record in records:
            if record["call_index"] in seen:
                continue
            seen.add(record["call_index"])
            item["rejected_model_calls"] += int(record.get("harness_rejected", False))
            for tool in record.get("tool_requests", []):
                tool_name = tool.get("tool_name", tool.get("tool"))
                if isinstance(tool_name, str):
                    item["tool_counts"][tool_name] = (
                        item["tool_counts"].get(tool_name, 0) + 1
                    )

    def recover(self):
        """A backend restart preserves partial work; it never resumes with new weights."""
        if not self.root.exists():
            return
        for path in self.root.iterdir():
            if not path.is_dir() or path.is_symlink():
                continue
            group = None
            try:
                group = self.get(path.name)
                if group["status"] not in {"preparing", "running"}:
                    continue
                with self._lock:
                    _, manifest, _ = self._read(path.name)
                    for item in manifest["trajectories"]:
                        self.recount(
                            item,
                            self.read_calls(
                                path / f"trajectory_{item['trajectory']:02d}.jsonl"
                            ),
                        )
                    atomic_json(path / "manifest.json", manifest)
                for item in group["trajectories"]:
                    if item["status"] == "running":
                        self.update(
                            path.name,
                            trajectory=item["trajectory"],
                            trajectory_status="interrupted",
                        )
                self.update(
                    path.name,
                    status="interrupted",
                    stopping=False,
                    error="Backend restarted. Saved calls were preserved; start a new collection.",
                )
            except (ValueError, OSError, KeyError) as exc:
                if group is None:
                    continue
                try:
                    for item in group["trajectories"]:
                        if item["status"] == "running":
                            self.update(
                                path.name,
                                trajectory=item["trajectory"],
                                trajectory_status="interrupted",
                            )
                    self.update(
                        path.name,
                        status="interrupted",
                        stopping=False,
                        error=f"Collection recovery found damaged storage: {exc}. Original files were preserved.",
                    )
                except (ValueError, OSError, KeyError):
                    continue
