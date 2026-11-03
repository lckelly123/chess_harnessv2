"""Offline, fixed-advantage clipped policy training with Unsloth.

This is a PPO/GRPO-style surrogate, not group-relative reward calculation. A is
supplied unchanged by the caller. No generation, reward calculation, baseline,
KL penalty, deduplication, or retokenization happens here.

Inputs: --adapter-path, --data (capture directories or JSONL files), and either
an inline numeric "A" on every record or --advantages pointing to JSONL like:
    {"run_id": "<run UUID>", "call_index": 3, "A": -1.0}
Omit call_index to assign A to a whole trajectory/run. A per-call entry overrides
a per-run entry. With a sidecar, ONLY matched calls are selected. This lets the
caller select one failed attempt per input without changing the source captures.

Each data file needs its original capture_config.json beside it, or an explicit
--capture-config. Old log probabilities must be RAW model log-softmax values.
The ratio is current_raw_policy / old_raw_policy, not current / filtered sampler.
No correction for temperature/top-k/top-p sampling or selected-data bias is
applied: this is the requested offline surrogate, not unbiased on-policy GRPO.

Use --validate-only to check all inputs without importing Unsloth/PyTorch,
loading weights, creating output files, or using the GPU. See docs/grpo-training.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

RAW_LOGPROBS = "natural_log_softmax_raw_model_logits"
TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")


@dataclass
class Sample:
    key: tuple[str, int]
    prompt: list[int]
    completion: list[int]
    old_logprobs: list[float]
    mask: list[int]
    advantage: float
    source: str


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def jsonl(path: Path):
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            location = f"{path}:{line_number}"
            try:
                value = json.loads(line)
            except ValueError as error:
                raise ValueError(f"{location}: invalid JSON: {error}") from error
            if not isinstance(value, dict):
                raise ValueError(f"{location}: expected an object")
            yield location, value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def number(value, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{location}: expected a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{location}: expected a finite number")
    return float(value)


def key_for(record: dict, location: str, *, run_allowed=False):
    run_id = record.get("run_id")
    call = record.get("call_index")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError(f"{location}: run_id must be a nonempty string")
    if call is None and run_allowed:
        return run_id, None
    if type(call) is not int or call < 1:
        raise ValueError(f"{location}: call_index must be a positive integer")
    return run_id, call


def load_advantages(path: Path | None):
    if path is None:
        return None
    result = {}
    for location, row in jsonl(path):
        key = key_for(row, location, run_allowed=True)
        if key in result:
            raise ValueError(f"{location}: duplicate advantage for {key}")
        result[key] = number(row.get("A"), f"{location} A")
    if not result:
        raise ValueError("The advantages file is empty")
    return result


def validate_sample(row: dict, advantage: float, location: str, max_length: int):
    # Harness failure is a valid negative example; generation/capture failure is not.
    if row.get("capture_valid") is not True or row.get("status") != "completed":
        raise ValueError(f"{location}: selected call has an incomplete/invalid capture")
    if row.get("error") or row.get("prompt_truncated") or row.get("truncated"):
        raise ValueError(f"{location}: selected call has a generation error/truncation")
    if row.get("finish_reason") not in {"stop", "eos"}:
        raise ValueError(f"{location}: selected call did not finish normally")
    arrays = []
    for field in ("prompt_token_ids", "completion_token_ids"):
        tokens = row.get(field)
        if not isinstance(tokens, list) or not tokens:
            raise ValueError(f"{location}: {field} must be a nonempty list")
        if any(type(token) is not int or token < 0 for token in tokens):
            raise ValueError(f"{location}: {field} contains an invalid token ID")
        arrays.append(tokens)
    prompt, completion = arrays
    if len(prompt) + len(completion) > max_length:
        raise ValueError(
            f"{location}: sequence exceeds {max_length}; never truncate replay"
        )
    old = row.get("old_logprobs")
    if not isinstance(old, list) or len(old) != len(completion):
        raise ValueError(
            f"{location}: old_logprobs must align with completion_token_ids"
        )
    old = [number(x, f"{location} old_logprobs") for x in old]
    if any(x > 0 for x in old):
        raise ValueError(f"{location}: log probabilities cannot be positive")
    mask = row.get("completion_mask", [1] * len(completion))
    if (
        not isinstance(mask, list)
        or len(mask) != len(completion)
        or any(type(x) is not int or x not in (0, 1) for x in mask)
        or not any(mask)
    ):
        raise ValueError(f"{location}: completion_mask must contain aligned 0/1 values")
    return Sample(
        key_for(row, location), prompt, completion, old, mask, advantage, location
    )


def load_data(paths, advantages, capture_config, max_length):
    files = []
    for supplied in paths:
        path = Path(supplied).resolve()
        candidates = (
            sorted(path.glob("trajectory_*.jsonl")) if path.is_dir() else [path]
        )
        if not candidates:
            raise ValueError(f"{path}: no trajectory JSONL files found")
        for candidate in candidates:
            if not candidate.is_file() or candidate in files:
                raise ValueError(f"Missing or duplicate data file: {candidate}")
            files.append(candidate)
    samples, metadata, seen, used = [], {}, set(), set()
    excluded = 0
    for path in files:
        selected_here = False
        for location, row in jsonl(path):
            key = key_for(row, location)
            if key in seen:
                raise ValueError(f"{location}: duplicate model-call identity {key}")
            seen.add(key)
            if advantages is None:
                advantage = number(row.get("A"), f"{location} A (required)")
            else:
                run_key = (key[0], None)
                matches = [k for k in (run_key, key) if k in advantages]
                if not matches:
                    excluded += 1
                    continue
                used.update(matches)
                if "A" in row:
                    raise ValueError(
                        f"{location}: choose inline A OR a sidecar, not both"
                    )
                advantage = advantages[matches[-1]]
            samples.append(validate_sample(row, advantage, location, max_length))
            selected_here = True
        if selected_here:
            config_path = (
                Path(capture_config).resolve()
                if capture_config
                else path.parent / "capture_config.json"
            )
            if config_path not in metadata:
                config = read_json(config_path)
                worker = config.get("capture_worker")
                if not isinstance(worker, dict):
                    raise ValueError(
                        f"{config_path}: capture_worker metadata is required"
                    )
                if worker.get("old_logprobs_convention") != RAW_LOGPROBS:
                    raise ValueError(f"{config_path}: expected RAW policy old_logprobs")
                metadata[config_path] = worker
    if advantages is not None and used != set(advantages):
        missing = sorted(set(advantages) - used, key=str)
        raise ValueError(f"Advantages reference missing calls/runs: {missing[:5]}")
    if not samples or not any(sample.advantage != 0 for sample in samples):
        raise ValueError("Select at least one call with a nonzero supplied A")
    return samples, metadata, files, excluded


def check_adapter(adapter: Path, metadata: dict, allow_mismatch: bool):
    config = read_json(adapter / "adapter_config.json")
    if config.get("peft_type") != "LORA":
        raise ValueError("This trainer requires an existing LoRA/QLoRA adapter")
    if config.get("bias", "none") != "none" or config.get("modules_to_save"):
        raise ValueError(
            "This version updates LoRA parameters only (no bias/modules_to_save)"
        )
    if config.get("use_dora"):
        raise ValueError("DoRA is not supported by this version")
    base = config.get("base_model_name_or_path")
    if not isinstance(base, str) or not base:
        raise ValueError("Adapter config must identify its base model")
    adapter_hash = sha256(adapter / "adapter_model.safetensors")
    revisions, mismatches = set(), []
    for source, worker in metadata.items():
        if worker.get("base_model", "").lower() != base.lower():
            raise ValueError(
                f"{source}: captured base model differs from starting adapter"
            )
        revision = worker.get("base_model_revision")
        if not isinstance(revision, str) or not revision:
            raise ValueError(f"{source}: a pinned base_model_revision is required")
        revisions.add(revision)
        captured_hash = worker.get("adapter_sha256")
        if not isinstance(captured_hash, str) or len(captured_hash) != 64:
            raise ValueError(f"{source}: missing captured adapter SHA256")
        if captured_hash != adapter_hash:
            mismatches.append(str(source))
        hashes = worker.get("file_sha256", {})
        if not hashes.get("tokenizer.json"):
            raise ValueError(f"{source}: tokenizer fingerprint is required")
        for name in TOKENIZER_FILES:
            if name in hashes and sha256(adapter / name) != hashes[name]:
                raise ValueError(
                    f"{source}: {name} differs from the captured tokenizer"
                )
    if len(revisions) != 1:
        raise ValueError("All selected captures must use the same pinned base revision")
    if mismatches and not allow_mismatch:
        raise ValueError(
            "Starting adapter differs from the collection policy. Supply the original "
            "adapter, or --allow-adapter-mismatch for an intentional off-policy start. "
            "Saved old_logprobs will remain unchanged."
        )
    return {
        "base_model": base,
        "base_model_revision": next(iter(revisions)),
        "adapter_sha256": adapter_hash,
        "off_policy_start": bool(mismatches),
    }


def check_output(output: Path, adapter: Path, data_files):
    if output.exists():
        raise ValueError(
            f"Output already exists; choose a new checkpoint directory: {output}"
        )
    if output.is_relative_to(adapter) or adapter.is_relative_to(output):
        raise ValueError("Output must be separate from the starting adapter")
    if any(path.is_relative_to(output) for path in data_files):
        raise ValueError("Output must not contain input data")


def clipped_policy_loss(current, old, advantage: float, mask, epsilon: float):
    """Mean over active completion tokens; old policy and A are constants."""
    import torch

    active = mask.bool()
    log_ratio = current.float()[active] - old.detach().float()[active]
    ratio = log_ratio.exp()
    if not torch.isfinite(ratio).all():
        raise ValueError(
            "Nonfinite probability ratio; inspect stale data/model mismatch"
        )
    surrogate = torch.minimum(
        ratio * advantage, ratio.clamp(1 - epsilon, 1 + epsilon) * advantage
    )
    loss = -surrogate.mean()
    clipped = (ratio > 1 + epsilon) if advantage > 0 else (ratio < 1 - epsilon)
    metrics = {
        "loss": loss.detach().item(),
        "ratio_mean": ratio.detach().mean().item(),
        "clip_fraction": clipped.float().mean().item() if advantage else 0.0,
        "mean_abs_log_ratio": log_ratio.detach().abs().mean().item(),
    }
    return loss, metrics


def completion_logprobs(model, sample: Sample, device, chunk_size: int, transform):
    """Teacher force exact tokens, checkpointing the vocabulary projection.

    Input ends one token early. Its last C hidden states predict all C completion
    tokens, including the FIRST generated token and the recorded EOS. Unsloth's
    hidden-state return avoids allocating prompt-length vocabulary logits.
    """
    import torch
    from torch.utils.checkpoint import checkpoint

    ids = torch.tensor(
        [sample.prompt + sample.completion[:-1]], dtype=torch.long, device=device
    )
    targets = torch.tensor(sample.completion, dtype=torch.long, device=device)
    output = model(
        input_ids=ids,
        attention_mask=torch.ones_like(ids),
        position_ids=torch.arange(ids.shape[1], device=device).unsqueeze(0),
        use_cache=False,
        return_dict=True,
        logits_to_keep=len(sample.completion),
    )
    hidden = output.logits
    head = model.get_output_embeddings()
    expected = (1, len(sample.completion), head.weight.shape[1])
    if tuple(hidden.shape) != expected:
        raise ValueError(
            "Unsloth hidden-state return is unavailable for this model/version; "
            f"expected {expected}, received {tuple(hidden.shape)}"
        )

    def project(states, token_ids):
        logits = transform(head(states.to(head.weight.dtype)))
        return -torch.nn.functional.cross_entropy(
            logits.float(), token_ids, reduction="none"
        )

    chunks = []
    for start in range(0, len(sample.completion), chunk_size):
        end = start + chunk_size
        chunks.append(
            checkpoint(
                project, hidden[0, start:end], targets[start:end], use_reentrant=False
            )
        )
    return torch.cat(chunks)


def load_model(args, identity):
    # Set before imports; no import/model/GPU work occurs in validation mode.
    os.environ["UNSLOTH_RETURN_HIDDEN_STATES"] = "1"
    from unsloth import FastLanguageModel

    # isort: split
    # Unsloth must patch the libraries before PEFT/Transformers are imported.
    import torch
    from peft import PeftModel
    from transformers import AutoTokenizer
    from unsloth.models.llama import apply_logit_transforms, resolve_logit_scaling

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ValueError("This trainer requires a CUDA GPU with BF16 support")
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    # Load the PINNED base separately: loading an adapter directly can resolve
    # the base's latest revision instead of the one recorded at collection time.
    base, _ = FastLanguageModel.from_pretrained(
        model_name=identity["base_model"],
        revision=identity["base_model_revision"],
        use_exact_model_name=True,
        max_seq_length=args.max_seq_length,
        dtype=torch.bfloat16,
        load_in_4bit=True,
        fast_inference=False,
        use_gradient_checkpointing="unsloth",
        local_files_only=not args.allow_download,
        trust_remote_code=False,
    )
    # This hidden-state path matches the installed Unsloth Llama/Qwen forward.
    if base.config.model_type not in {"qwen3", "qwen2", "llama"}:
        raise ValueError("This version supports dense Qwen3, Qwen2 and Llama models")
    model = PeftModel.from_pretrained(
        base, str(args.adapter_path), is_trainable=True, local_files_only=True
    )
    model = FastLanguageModel.patch_peft_model(
        model, use_gradient_checkpointing="unsloth"
    )
    tokenizer = AutoTokenizer.from_pretrained(
        str(args.adapter_path), local_files_only=True, trust_remote_code=False
    )
    FastLanguageModel.for_training(model, use_gradient_checkpointing="unsloth")
    model.config.use_cache = False
    # Dropout changes the policy used for the ratio. Keep checkpointing/training
    # enabled while disabling both module and functional attention dropout.
    for module in model.modules():
        if isinstance(module, torch.nn.Dropout):
            module.p = 0.0
        if isinstance(getattr(module, "attention_dropout", None), (int, float)):
            module.attention_dropout = 0.0
    params = []
    for name, parameter in model.named_parameters():
        trainable = ".lora_A." in name or ".lora_B." in name
        parameter.requires_grad_(trainable)
        if trainable:
            params.append(parameter)
    if not params:
        raise ValueError("Loaded adapter has no trainable LoRA matrices")
    softcap, scaling = resolve_logit_scaling(model.config)

    def transform(logits):
        return apply_logit_transforms(logits, softcap, scaling)

    return model, tokenizer, params, transform


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def train(args, samples, identity, report):
    model, tokenizer, params, transform = load_model(args, identity)
    import torch

    vocabulary_size = model.get_input_embeddings().weight.shape[0]
    for sample in samples:
        if max(sample.prompt + sample.completion) >= vocabulary_size:
            raise ValueError(f"{sample.source}: token ID outside the model vocabulary")
    device = model.get_input_embeddings().weight.device
    if args.optimizer == "adamw8bit":
        from bitsandbytes.optim import AdamW8bit

        optimizer = AdamW8bit(params, lr=args.learning_rate, weight_decay=0.0)
    else:
        optimizer = torch.optim.AdamW(params, lr=args.learning_rate, weight_decay=0.0)
    # Atomic creation prevents accidental overwrites, including concurrent jobs.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report.update(status="running", started_at=utc_now(), optimizer_steps=0)
    report["trainable_parameters"] = sum(p.numel() for p in params)
    from importlib.metadata import version

    report["packages"] = {
        name: version(name) for name in ("torch", "unsloth", "peft", "transformers")
    }
    write_json(args.output_dir / "training_run.json", report)
    rng = random.Random(args.seed)
    optimizer.zero_grad(set_to_none=True)
    steps = 0
    try:
        with (args.output_dir / "metrics.jsonl").open("x", encoding="utf-8") as log:
            for epoch in range(args.epochs):
                order = list(samples)
                rng.shuffle(order)
                for start in range(0, len(order), args.gradient_accumulation_steps):
                    group = order[start : start + args.gradient_accumulation_steps]
                    metrics = Counter()
                    nonzero = 0
                    for sample in group:
                        if sample.advantage == 0:
                            continue
                        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                            current = completion_logprobs(
                                model,
                                sample,
                                device,
                                args.logprob_chunk_size,
                                transform,
                            )
                            old = torch.tensor(
                                sample.old_logprobs, device=device, dtype=torch.float32
                            )
                            mask = torch.tensor(
                                sample.mask, device=device, dtype=torch.bool
                            )
                            loss, call_metrics = clipped_policy_loss(
                                current, old, sample.advantage, mask, args.clip_epsilon
                            )
                        if not torch.isfinite(loss):
                            raise ValueError(f"{sample.source}: nonfinite loss")
                        # Equal weight per call; also correct for a final short group.
                        (loss / len(group)).backward()
                        metrics.update(call_metrics)
                        nonzero += 1
                        del current, old, mask, loss
                    if not nonzero:
                        continue
                    norm = torch.nn.utils.clip_grad_norm_(
                        params, args.max_grad_norm, error_if_nonfinite=True
                    )
                    optimizer.step()
                    optimizer.zero_grad(set_to_none=True)
                    steps += 1
                    row = {
                        "step": steps,
                        "epoch": epoch + 1,
                        "calls": len(group),
                        "loss": metrics["loss"] / len(group),
                        "ratio_mean": metrics["ratio_mean"] / nonzero,
                        "clip_fraction": metrics["clip_fraction"] / nonzero,
                        "mean_abs_log_ratio": metrics["mean_abs_log_ratio"] / nonzero,
                        "gradient_norm": float(norm),
                        "peak_vram_gib": torch.cuda.max_memory_allocated() / 2**30,
                    }
                    log.write(json.dumps(row, allow_nan=False) + "\n")
                    log.flush()
                    print(json.dumps(row), flush=True)
                    if args.max_steps and steps >= args.max_steps:
                        break
                if args.max_steps and steps >= args.max_steps:
                    break
        model.save_pretrained(str(args.output_dir), safe_serialization=True)
        tokenizer.save_pretrained(str(args.output_dir))
        saved_config = read_json(args.output_dir / "adapter_config.json")
        saved_config.update(
            unsloth_training_method="fixed_advantage_rl", unsloth_load_in_4bit=True
        )
        write_json(args.output_dir / "adapter_config.json", saved_config)
        report.update(status="completed", finished_at=utc_now(), optimizer_steps=steps)
    except BaseException as error:
        report.update(
            status="failed",
            finished_at=utc_now(),
            optimizer_steps=steps,
            error=str(error),
        )
        raise
    finally:
        write_json(args.output_dir / "training_run.json", report)


def parser():
    result = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    result.add_argument(
        "--adapter-path",
        required=True,
        type=Path,
        help="Existing QLoRA checkpoint to update",
    )
    result.add_argument(
        "--data",
        required=True,
        nargs="+",
        type=Path,
        help="Capture directories or prepared JSONL files",
    )
    result.add_argument(
        "--advantages",
        type=Path,
        help="Supplied A values/selection as JSONL; otherwise require inline A",
    )
    result.add_argument(
        "--capture-config",
        type=Path,
        help="Original capture_config.json for relocated/prepared data",
    )
    result.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="New directory for the updated adapter",
    )
    result.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate inputs only; no model, GPU, or output writes",
    )
    result.add_argument(
        "--allow-adapter-mismatch",
        action="store_true",
        help="Intentionally start from a different adapter than collection",
    )
    result.add_argument(
        "--allow-download",
        action="store_true",
        help="Permit downloading the pinned base; default uses local cache",
    )
    result.add_argument("--learning-rate", type=float, default=5e-6)
    result.add_argument("--clip-epsilon", type=float, default=0.2)
    result.add_argument("--gradient-accumulation-steps", type=int, default=8)
    result.add_argument("--epochs", type=int, default=1)
    result.add_argument(
        "--max-steps",
        type=int,
        default=0,
        help="Optimizer-step cap; 0 uses the requested epochs",
    )
    result.add_argument("--max-seq-length", type=int, default=8192)
    result.add_argument(
        "--logprob-chunk-size",
        type=int,
        default=64,
        help="Completion tokens per checkpointed vocabulary projection",
    )
    result.add_argument("--max-grad-norm", type=float, default=1.0)
    result.add_argument(
        "--optimizer", choices=("adamw8bit", "adamw"), default="adamw8bit"
    )
    result.add_argument("--seed", type=int, default=3407)
    return result


def prepare(args):
    for name in ("learning_rate", "max_grad_norm"):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if not 0 < args.clip_epsilon < 1:
        raise ValueError("clip_epsilon must be between 0 and 1")
    for name in (
        "gradient_accumulation_steps",
        "epochs",
        "max_seq_length",
        "logprob_chunk_size",
    ):
        if getattr(args, name) < 1:
            raise ValueError(f"{name} must be positive")
    if args.max_steps < 0 or not 0 <= args.seed < 2**32:
        raise ValueError("max_steps must be nonnegative and seed must be in [0, 2**32)")
    args.adapter_path = args.adapter_path.resolve()
    args.output_dir = args.output_dir.resolve()
    advantages = load_advantages(args.advantages)
    samples, metadata, files, excluded = load_data(
        args.data, advantages, args.capture_config, args.max_seq_length
    )
    identity = check_adapter(args.adapter_path, metadata, args.allow_adapter_mismatch)
    check_output(args.output_dir, args.adapter_path, files)
    report = {
        "algorithm": "fixed_advantage_clipped_raw_policy_surrogate",
        "kl_coefficient": 0,
        "advantage_normalization": "none",
        "loss_reduction": "mean active completion tokens per call, then mean calls",
        "sampling_correction": "none; filtered and selected offline data",
        "identity": identity,
        "settings": {
            k: str(v) if isinstance(v, Path) else v
            for k, v in vars(args).items()
            if k != "data"
        },
        "data": [{"path": str(p), "sha256": sha256(p)} for p in files],
        "advantages_sha256": sha256(args.advantages) if args.advantages else None,
        "capture_metadata": {str(p): value for p, value in metadata.items()},
        "selected_calls": len(samples),
        "excluded_unselected_calls": excluded,
        "positive_A": sum(s.advantage > 0 for s in samples),
        "negative_A": sum(s.advantage < 0 for s in samples),
        "zero_A": sum(s.advantage == 0 for s in samples),
        "active_completion_tokens": sum(sum(s.mask) for s in samples),
        "max_sequence_tokens": max(len(s.prompt) + len(s.completion) for s in samples),
    }
    return samples, identity, report


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        samples, identity, report = prepare(args)
        print(
            json.dumps(
                {
                    "validation": "passed",
                    "selected_calls": report["selected_calls"],
                    "positive_A": report["positive_A"],
                    "negative_A": report["negative_A"],
                    "zero_A": report["zero_A"],
                    "max_sequence_tokens": report["max_sequence_tokens"],
                    "off_policy_start": identity["off_policy_start"],
                }
            ),
            flush=True,
        )
        if args.validate_only:
            print(
                "Validation only: no model loaded, no training started, no output written."
            )
            return 0
        train(args, samples, identity, report)
        return 0
    except (ValueError, OSError) as error:
        print(f"GRPO_trainer: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
