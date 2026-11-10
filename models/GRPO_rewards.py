"""CPU-only CP-loss rewards for captured model calls. No training or file writes.

Normalize over the entire collection, not over calls/minibatches. Failed runs
receive the worst completed run's CP loss. For each call, subtract 2 if the
harness rejected it, then clamp to [-1, 1]. Equal losses give a base score of 0.
An all-failed batch has no engine baseline and is rejected rather than guessed.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

DEFAULT_HARNESS_PENALTY = 2.0


def finite_number(value, label):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def trajectory_advantages(trajectories):
    """Return run_id -> base A using every trajectory in one position's batch.

    trajectories is {run_id: {status: 'completed'|'failed', cp_loss: number|None}}.
    A failed trajectory's stored cp_loss is ignored; completed runs require a
    finite nonnegative engine loss. This is min-max scaling, not mean centering.
    """
    if not trajectories:
        raise ValueError("The reward batch is empty")
    completed = {}
    for run_id, result in trajectories.items():
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("Every trajectory needs a nonempty run_id")
        status = result.get("status")
        if status == "completed":
            loss = finite_number(result.get("cp_loss"), f"{run_id} cp_loss")
            if loss < 0:
                raise ValueError(f"{run_id} cp_loss must be nonnegative")
            completed[run_id] = loss
        elif status != "failed":
            raise ValueError(f"{run_id}: reward requires a completed or failed run")
    if not completed:
        raise ValueError(
            "No completed trajectory with CP loss; cannot define worst loss"
        )
    low, high = min(completed.values()), max(completed.values())
    return {
        run_id: (
            0.0
            if high == low
            else 1.0 - 2.0 * (completed.get(run_id, high) - low) / (high - low)
        )
        for run_id in trajectories
    }


def advantage_for_pass(
    trajectory_advantage, harness_rejected, harness_penalty=DEFAULT_HARNESS_PENALTY
):
    """One scalar A for all generated tokens in this model pass."""
    base = finite_number(trajectory_advantage, "trajectory advantage")
    penalty = finite_number(harness_penalty, "harness penalty")
    if not -1 <= base <= 1 or penalty < 0:
        raise ValueError(
            "Base advantage must be in [-1, 1]; harness penalty must be >= 0"
        )
    if type(harness_rejected) is not bool:
        raise ValueError("Each call needs a boolean harness_rejected label")
    return max(-1.0, min(1.0, base - penalty * harness_rejected))


def calculate_advantages(calls, trajectories, harness_penalty=DEFAULT_HARNESS_PENALTY):
    """Return {(run_id, call_index): A} without modifying or deduplicating calls."""
    bases = trajectory_advantages(trajectories)
    result = {}
    for call in calls:
        run_id, index = call.get("run_id"), call.get("call_index")
        if not isinstance(run_id, str) or run_id not in bases:
            raise ValueError(f"Call refers to an unknown trajectory: {run_id!r}")
        if type(index) is not int or index < 1:
            raise ValueError("Every call needs a positive integer call_index")
        key = (run_id, index)
        if key in result:
            raise ValueError(f"Duplicate reward selector: {key}")
        result[key] = advantage_for_pass(
            bases[run_id], call.get("harness_rejected"), harness_penalty
        )
    return result


def read_calls(path):
    with Path(path).open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_number}: expected a JSON object")
                yield row


def load_collection_results(root):
    """Bind manifest trajectory numbers to original capture run IDs, never order
    the prepared rows or infer a whole-run failure from a single rejected call.
    """
    root = Path(root)
    manifest_path = root / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    entries = manifest.get("trajectories")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{manifest_path}: a complete trajectory manifest is required")
    hashes = {"manifest.json": hashlib.sha256(manifest_bytes).hexdigest()}
    results, numbers = {}, set()
    for entry in entries:
        number = entry.get("trajectory")
        if type(number) is not int or number < 1 or number in numbers:
            raise ValueError(f"{manifest_path}: invalid or duplicate trajectory number")
        numbers.add(number)
        path = root / f"trajectory_{number:02d}.jsonl"
        data = path.read_bytes()
        hashes[path.name] = hashlib.sha256(data).hexdigest()
        rows = [json.loads(line) for line in data.splitlines() if line.strip()]
        if not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError(
                f"{path}: original calls are required to resolve the run_id"
            )
        run_ids = {row.get("run_id") for row in rows}
        if len(run_ids) != 1:
            raise ValueError(f"{path}: expected exactly one run_id")
        run_id = run_ids.pop()
        if not isinstance(run_id, str) or not run_id.strip() or run_id in results:
            raise ValueError(f"{path}: invalid or duplicate run_id")
        results[run_id] = {
            "trajectory": number,
            "status": entry.get("status"),
            "cp_loss": entry.get("cp_loss"),
        }
    return results, hashes


def supply_advantages(
    data_files, capture_config=None, harness_penalty=DEFAULT_HARNESS_PENALTY
):
    """Score selected calls, using all original runs for each collection's range.

    Prepared data stays untouched. Its original manifest and trajectory files
    live alongside it, or beside --capture-config when data has been relocated.
    The returned audit metadata can be saved in the trainer's run report.
    """
    groups = defaultdict(list)
    for supplied in data_files:
        path = Path(supplied).resolve()
        root = Path(capture_config).resolve().parent if capture_config else path.parent
        groups[root].extend(read_calls(path))
    advantages, batches = {}, []
    for root, calls in groups.items():
        if any("A" in call for call in calls):
            raise ValueError("Choose supplied A values OR calculated CP-loss rewards")
        trajectories, hashes = load_collection_results(root)
        values = calculate_advantages(calls, trajectories, harness_penalty)
        if advantages.keys() & values.keys():
            raise ValueError("A model call appears in more than one reward batch")
        advantages.update(values)
        bases = trajectory_advantages(trajectories)
        completed_losses = [
            r["cp_loss"] for r in trajectories.values() if r["status"] == "completed"
        ]
        by_run = defaultdict(list)
        for call in calls:
            by_run[call["run_id"]].append(call)
        per_trajectory = []
        for run_id, result in trajectories.items():
            selected = by_run[run_id]
            per_trajectory.append(
                {
                    "run_id": run_id,
                    **result,
                    "effective_cp_loss": result["cp_loss"]
                    if result["status"] == "completed"
                    else max(completed_losses),
                    "base_advantage": bases[run_id],
                    "selected_calls": len(selected),
                    "rejected_calls": sum(c["harness_rejected"] for c in selected),
                    "accepted_call_A": advantage_for_pass(
                        bases[run_id], False, harness_penalty
                    ),
                    "rejected_call_A": advantage_for_pass(
                        bases[run_id], True, harness_penalty
                    ),
                }
            )
        batches.append(
            {
                "collection": str(root),
                "source_sha256": hashes,
                "min_cp_loss": min(completed_losses),
                "max_cp_loss": max(completed_losses),
                "trajectories": per_trajectory,
            }
        )
    return advantages, {
        "source": "cp_loss_helper",
        "normalization": "trajectory_batch_min_max_to_minus1_plus1",
        "formula": "clip(1 - 2*(effective_cp_loss-min)/(max-min) - lambda*rejected, -1, 1)",
        "harness_penalty": harness_penalty,
        "equal_loss_base_advantage": 0.0,
        "failed_trajectory_policy": "worst_completed_cp_loss",
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "batches": batches,
    }
