"""A single resident Unsloth policy, with selected-token probabilities on CPU.

Run this on the GPU host with its Unsloth Python environment. The main web
backend calls it over HTTP; it never imports torch or loads the policy itself.
No training, gradients, optimizer, or model updates happen in this worker.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import hmac
import json
import math
import os
import re
import threading
import time
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field


class SamplingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float = Field(default=0.6, gt=0, le=5, allow_inf_nan=False)
    top_p: float = Field(default=0.95, gt=0, le=1, allow_inf_nan=False)
    top_k: int = Field(default=20, ge=0, le=1000)
    repetition_penalty: float = Field(default=1.0, gt=0, le=3, allow_inf_nan=False)
    enable_thinking: bool = False


class PrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str = Field(min_length=1, max_length=240)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    max_seq_length: int = Field(default=8192, ge=128, le=32768)
    sampling: SamplingSettings = Field(default_factory=SamplingSettings)


class CompleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    request: dict[str, Any]
    seed: int = Field(ge=0, le=2**63 - 1)
    request_id: str = Field(default_factory=lambda: uuid4().hex, max_length=128)
    timeout_seconds: float = Field(default=600, gt=0, le=3600, allow_inf_nan=False)


class SessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str


def resolve_adapter(root: Path, name: str) -> Path:
    """Resolve a selected Studio output name, never an arbitrary filesystem path."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,239}", name):
        raise ValueError("Select a local Unsloth adapter by its output folder name.")
    resolved_root = root.resolve()
    target = (resolved_root / name).resolve()
    if target.parent != resolved_root:
        raise ValueError("The adapter must be inside the configured output directory.")
    if not (target / "adapter_config.json").is_file():
        raise ValueError("The selected output does not contain adapter_config.json.")
    if not (target / "adapter_model.safetensors").is_file():
        raise ValueError(
            "The selected output does not contain adapter_model.safetensors."
        )
    return target


def fingerprint(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def text_messages(request: dict[str, Any]) -> list[dict[str, str]]:
    if request.get("tools") or request.get("tool_choice"):
        raise ValueError("GRPO capture currently supports the text-tool chess_harness.")
    messages = request.get("input")
    if not isinstance(messages, list) or not messages:
        raise ValueError(
            "The model request must contain a nonempty input message list."
        )
    converted = []
    for item in messages:
        if not isinstance(item, dict):
            raise ValueError("Input messages must be objects.")
        role = item.get("role")
        if role not in {"system", "developer", "user", "assistant"}:
            raise ValueError("Only text messages are supported by GRPO capture.")
        content = item.get("content")
        if isinstance(content, list):
            if any(
                not isinstance(part, dict)
                or part.get("type") not in {"input_text", "output_text", "text"}
                or not isinstance(part.get("text"), str)
                for part in content
            ):
                raise ValueError("GRPO capture accepts text input only.")
            content = "".join(part["text"] for part in content)
        if not isinstance(content, str):
            raise ValueError("Each input message needs text content.")
        converted.append(
            {"role": "system" if role == "developer" else role, "content": content}
        )
    return converted


def sampling_scores(torch, logits, seen_ids: list[int], settings: SamplingSettings):
    """Transform one vocabulary vector; never retain vectors across token steps."""
    scores = logits.clone()
    if settings.repetition_penalty != 1 and seen_ids:
        indices = torch.tensor(sorted(set(seen_ids)), device=scores.device)
        selected = scores[indices]
        scores[indices] = torch.where(
            selected < 0,
            selected * settings.repetition_penalty,
            selected / settings.repetition_penalty,
        )
    scores /= settings.temperature
    if settings.top_k:
        threshold = torch.topk(scores, min(settings.top_k, scores.numel())).values[-1]
        scores.masked_fill_(scores < threshold, -float("inf"))
    if settings.top_p < 1:
        ordered, indices = torch.sort(scores, descending=True)
        cumulative = torch.softmax(ordered, dim=-1).cumsum(dim=-1)
        remove = cumulative > settings.top_p
        # Keep the token which first crosses the threshold, and at least one.
        remove[1:] = remove[:-1].clone()
        remove[0] = False
        scores[indices[remove]] = -float("inf")
    return scores


def validate_capture(capture: dict[str, Any]) -> None:
    ids = capture["completion_token_ids"]
    if len(ids) != len(capture["old_logprobs"]) or len(ids) != len(
        capture["sampling_logprobs"]
    ):
        raise ValueError("Capture token/probability alignment was lost.")
    if any(type(token) is not int or token < 0 for token in ids):
        raise ValueError("Capture contains an invalid generated token ID.")
    if any(
        not math.isfinite(value) or value > 1e-5
        for key in ("old_logprobs", "sampling_logprobs")
        for value in capture[key]
    ):
        raise ValueError("Capture contains an invalid selected-token log probability.")


def response_payload(model_name: str, capture: dict, decoded_text: str) -> dict:
    """Expose parsed text to the harness while retaining raw generation in capture."""
    reasoning = ""
    text = decoded_text
    if "</think>" in text:
        reasoning, text = text.split("</think>", 1)
        reasoning = reasoning.removeprefix("<think>").strip()
        text = text.lstrip("\n")
    output = []
    if reasoning:
        output.append(
            {
                "type": "reasoning",
                "id": f"rs_{uuid4().hex}",
                "summary": [],
                "content": [{"type": "reasoning_text", "text": reasoning}],
            }
        )
    status = "completed"
    if capture["finish_reason"] in {"error", "timeout", "cancelled"}:
        status = "cancelled" if capture["finish_reason"] == "cancelled" else "failed"
    elif capture["finish_reason"] in {"length", "context_length"}:
        status = "incomplete"
    output.append(
        {
            "type": "message",
            "id": f"msg_{uuid4().hex}",
            "role": "assistant",
            "status": "completed" if status == "completed" else "incomplete",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }
    )
    return {
        "id": f"resp_{uuid4().hex}",
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "model": model_name,
        "output": output,
        "error": {"message": capture["error"]} if capture.get("error") else None,
        "incomplete_details": {"reason": "max_output_tokens"}
        if status == "incomplete"
        else None,
        "usage": {
            "input_tokens": len(capture["prompt_token_ids"]),
            "output_tokens": len(capture["completion_token_ids"]),
            "total_tokens": len(capture["prompt_token_ids"])
            + len(capture["completion_token_ids"]),
        },
    }


class UnslothEngine:
    def __init__(
        self, adapter: Path, settings: PrepareBody, cancelled: threading.Event
    ):
        # Import order matters to Unsloth's patching. Keep GPU imports lazy so the
        # health check works before loading a model and backend tests need no GPU.
        import torch
        from unsloth import FastLanguageModel

        self.torch = torch
        self.settings = settings
        self.model = None
        self.tokenizer = None
        if not torch.cuda.is_available():
            raise ValueError("GRPO capture requires a CUDA GPU in this worker.")
        free, _ = torch.cuda.mem_get_info()
        if free < 11 * 2**30:
            raise ValueError(
                "Less than 11 GiB of GPU memory is free. Unload the Studio model "
                "before loading the GRPO capture policy."
            )
        files = [adapter / "adapter_config.json", adapter / "adapter_model.safetensors"]
        files.extend(
            path
            for name in (
                "tokenizer.json",
                "tokenizer_config.json",
                "chat_template.jinja",
            )
            if (path := adapter / name).is_file()
        )
        before = {
            str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in files
        }
        hashes = {path.name: fingerprint(path) for path in files}
        config = json.loads((adapter / "adapter_config.json").read_text())
        if cancelled.is_set():
            raise ValueError("Capture preparation was cancelled.")
        try:
            self.model, self.tokenizer = FastLanguageModel.from_pretrained(
                model_name=str(adapter),
                max_seq_length=settings.max_seq_length,
                dtype=torch.bfloat16,
                load_in_4bit=True,
                local_files_only=True,
                trust_remote_code=False,
            )
            FastLanguageModel.for_inference(self.model)
            self.model.eval()
            for parameter in self.model.parameters():
                parameter.requires_grad_(False)
            if cancelled.is_set():
                raise ValueError("Capture preparation was cancelled.")
            after = {
                str(path): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in files
            }
            if before != after:
                raise ValueError(
                    "The adapter changed while being loaded. Start a new collection."
                )
            base_name = config.get("base_model_name_or_path")
            base_revision = None
            try:
                from huggingface_hub import try_to_load_from_cache

                cached = try_to_load_from_cache(base_name, "config.json")
                if isinstance(cached, str) and "snapshots" in Path(cached).parts:
                    parts = Path(cached).parts
                    base_revision = parts[parts.index("snapshots") + 1]
            except (OSError, ValueError, TypeError):
                pass
            self.metadata = {
                "worker_protocol_version": 1,
                "model_name": settings.model_name,
                "base_model": base_name,
                "base_model_revision": base_revision,
                "adapter_path": str(adapter),
                "adapter_sha256": hashes["adapter_model.safetensors"],
                "file_sha256": hashes,
                "max_seq_length": settings.max_seq_length,
                "sampling": settings.sampling.model_dump(),
                "repetition_penalty_scope": "prompt_and_completion",
                "old_logprobs_convention": "natural_log_softmax_raw_model_logits",
                "sampling_logprobs_convention": (
                    "natural_log_softmax_after_repetition_penalty_temperature_top_k_top_p"
                ),
                "prompt_overflow_policy": "reject; never silently truncate instructions",
                "output_limit_policy": "min(requested_max_output_tokens, remaining_context)",
                "dtype": "bfloat16",
                "load_in_4bit": True,
                "weights_frozen": True,
            }
        except BaseException:
            self.close()
            raise

    def generate(self, body: CompleteBody, cancelled: threading.Event) -> dict:
        request = body.request
        if request.get("model", self.settings.model_name) != self.settings.model_name:
            raise ValueError(
                "This request names a different model than the frozen session."
            )
        messages = text_messages(request)
        requested = request.get("max_output_tokens", 2000)
        if type(requested) is not int or not 1 <= requested <= 32768:
            raise ValueError(
                "max_output_tokens must be an integer between 1 and 32768."
            )
        rendered = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=self.settings.sampling.enable_thinking,
        )
        prompt_ids = self.tokenizer.encode(rendered, add_special_tokens=False)
        capture = {
            "input": rendered,
            "prompt_token_ids": list(prompt_ids),
            "generated_response": "",
            "completion_token_ids": [],
            "old_logprobs": [],
            "sampling_logprobs": [],
            "finish_reason": "error",
            "status": "failed",
            "truncated": False,
            "prompt_truncated": False,
            "prompt_executed": False,
            "requested_max_output_tokens": requested,
            "effective_max_output_tokens": max(
                0, min(requested, self.settings.max_seq_length - len(prompt_ids))
            ),
            "seed": body.seed,
            "request_id": body.request_id,
            "error": None,
        }
        started = time.monotonic()
        try:
            if not prompt_ids:
                raise ValueError("The rendered prompt is empty.")
            if len(prompt_ids) >= self.settings.max_seq_length:
                raise ValueError(
                    f"The prompt has {len(prompt_ids)} tokens and fills the "
                    f"{self.settings.max_seq_length}-token context. No generation was attempted."
                )
            self._decode(capture, cancelled, started + body.timeout_seconds)
        except Exception as exc:
            capture.update(finish_reason="error", status="failed", error=str(exc))
        finally:
            capture["elapsed_seconds"] = round(time.monotonic() - started, 3)
        capture["generated_response"] = self.tokenizer.decode(
            capture["completion_token_ids"],
            skip_special_tokens=False,
            clean_up_tokenization_spaces=False,
        )
        visible = self.tokenizer.decode(
            capture["completion_token_ids"],
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
        validate_capture(capture)
        return {
            "response": response_payload(self.settings.model_name, capture, visible),
            "capture": capture,
        }

    def _decode(self, capture: dict, cancelled: threading.Event, deadline: float):
        torch = self.torch
        device = self.model.get_input_embeddings().weight.device
        prompt_ids = capture["prompt_token_ids"]
        ids = torch.tensor([prompt_ids], dtype=torch.long, device=device)
        attention = torch.ones_like(ids)
        generator = torch.Generator(device=device).manual_seed(capture["seed"])
        eos = self.model.generation_config.eos_token_id
        eos_ids = set(eos if isinstance(eos, list) else [eos])
        eos_ids.add(self.tokenizer.eos_token_id)
        past = None
        seen = list(prompt_ids)
        autocast = (
            torch.autocast(device_type="cuda", dtype=torch.bfloat16)
            if device.type == "cuda"
            else nullcontext()
        )
        with torch.inference_mode(), autocast:
            for _ in range(capture["effective_max_output_tokens"]):
                if cancelled.is_set():
                    capture.update(
                        finish_reason="cancelled",
                        status="cancelled",
                        error="Collection stopped.",
                    )
                    return
                if time.monotonic() >= deadline:
                    capture.update(
                        finish_reason="timeout",
                        status="failed",
                        error="Model call timed out.",
                    )
                    return
                capture["prompt_executed"] = True
                outputs = self.model(
                    input_ids=ids,
                    attention_mask=attention,
                    position_ids=(attention.cumsum(dim=-1) - 1)[:, -ids.shape[1] :],
                    past_key_values=past,
                    use_cache=True,
                    return_dict=True,
                    logits_to_keep=1,
                )
                past = outputs.past_key_values
                logits = outputs.logits[0, -1, :].float()
                del outputs
                scores = sampling_scores(torch, logits, seen, self.settings.sampling)
                probs = torch.softmax(scores, dim=-1)
                selected = torch.multinomial(probs, 1, generator=generator)
                token_id = int(selected.item())
                old_logp = float(
                    (logits[token_id] - torch.logsumexp(logits, -1)).item()
                )
                sampler_logp = float(
                    (scores[token_id] - torch.logsumexp(scores, -1)).item()
                )
                if not math.isfinite(old_logp) or not math.isfinite(sampler_logp):
                    raise ValueError(
                        "The model produced a non-finite selected-token log probability."
                    )
                # The three appends are adjacent, after both scores are known.
                # Only Python scalars persist across iterations, outside VRAM.
                capture["completion_token_ids"].append(token_id)
                capture["old_logprobs"].append(old_logp)
                capture["sampling_logprobs"].append(sampler_logp)
                seen.append(token_id)
                del logits, scores, probs
                # A long prompt prefill cannot be interrupted inside its CUDA
                # kernel. Preserve the sampled token, then honor a stop/deadline
                # which arrived while that forward pass was running.
                if cancelled.is_set():
                    capture.update(
                        finish_reason="cancelled",
                        status="cancelled",
                        error="Collection stopped.",
                    )
                    return
                if time.monotonic() >= deadline:
                    capture.update(
                        finish_reason="timeout",
                        status="failed",
                        error="Model call timed out.",
                    )
                    return
                if token_id in eos_ids:
                    capture.update(finish_reason="stop", status="completed")
                    return
                ids = selected.view(1, 1)
                attention = torch.cat((attention, torch.ones_like(ids)), dim=1)
            capture.update(
                finish_reason="context_length"
                if capture["effective_max_output_tokens"]
                < capture["requested_max_output_tokens"]
                else "length",
                status="incomplete",
                truncated=True,
            )

    def close(self):
        self.model = None
        self.tokenizer = None
        gc.collect()
        if self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()


class CaptureWorker:
    """One session owns the GPU until release; cancellation does not need its lock."""

    def __init__(self, adapter_root: Path, engine_factory: Callable = UnslothEngine):
        self.adapter_root = adapter_root
        self.engine_factory = engine_factory
        self.operation = threading.Lock()
        self.state = threading.RLock()
        self.cancelled = threading.Event()
        self.engine = None
        self.session_id = None
        self.model_name = None
        self.busy = False
        self.last_result = None

    def health(self) -> dict:
        with self.state:
            return {
                "service": "chess-grpo-capture",
                "protocol_version": 1,
                "ready": True,
                "busy": self.busy,
                "model_name": self.model_name,
                "session_id": self.session_id,
                "supported_harnesses": ["agent-player-2-langgraph-v1"],
            }

    def _session(self, session_id: str):
        if not self.session_id or not hmac.compare_digest(self.session_id, session_id):
            raise HTTPException(409, "The capture session is not active.")

    def prepare(self, body: PrepareBody) -> dict:
        adapter = resolve_adapter(self.adapter_root, body.model_name)
        if not self.operation.acquire(blocking=False):
            raise HTTPException(409, "The capture worker is busy.")
        try:
            with self.state:
                if self.session_id is not None:
                    raise HTTPException(
                        409, "Release the current capture session first."
                    )
                self.busy = True
                self.cancelled.clear()
                self.session_id = body.session_id or uuid4().hex
                self.model_name = body.model_name
                self.last_result = None
            try:
                self.engine = self.engine_factory(adapter, body, self.cancelled)
                return {
                    "session_id": self.session_id,
                    "model_name": self.model_name,
                    "metadata": self.engine.metadata,
                }
            except BaseException:
                with self.state:
                    self.engine = None
                    self.session_id = self.model_name = None
                raise
        finally:
            with self.state:
                self.busy = False
            self.operation.release()

    def complete(self, body: CompleteBody) -> dict:
        if not self.operation.acquire(blocking=False):
            raise HTTPException(409, "The capture worker is already generating.")
        try:
            with self.state:
                self._session(body.session_id)
                if self.engine is None:
                    raise HTTPException(409, "The capture model is not loaded.")
                self.busy = True
                self.last_result = None
            result = self.engine.generate(body, self.cancelled)
            with self.state:
                self.last_result = result
            return result
        finally:
            with self.state:
                self.busy = False
            self.operation.release()

    def cancel(self, body: SessionBody) -> dict:
        with self.state:
            self._session(body.session_id)
            self.cancelled.set()
            return {"status": "stopping", "busy": self.busy}

    def result(self, session_id: str, request_id: str | None) -> dict:
        with self.state:
            self._session(session_id)
            result = self.last_result
            if result and request_id and result["capture"]["request_id"] != request_id:
                result = None
            return {"busy": self.busy, "last_result": result}

    def release(self, body: SessionBody) -> dict:
        with self.state:
            self._session(body.session_id)
            self.cancelled.set()
        # Wait for generation to observe cancellation before freeing its model.
        with self.operation:
            with self.state:
                self._session(body.session_id)
                self.busy = True
            try:
                if self.engine is not None:
                    self.engine.close()
                return {"status": "released"}
            finally:
                with self.state:
                    self.engine = None
                    self.session_id = self.model_name = None
                    self.busy = False
                    self.last_result = None


def create_app(worker: CaptureWorker, token: str) -> FastAPI:
    if not token or len(token) < 32:
        raise ValueError(
            "A capture worker bearer token of at least 32 characters is required."
        )
    app = FastAPI(title="Chess GRPO capture worker", docs_url=None, redoc_url=None)

    def authenticate(authorization: str | None = Header(default=None)):
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not hmac.compare_digest(supplied, token):
            raise HTTPException(401, "Capture worker authentication failed.")

    @app.get("/health")
    def health():
        return worker.health()

    @app.post("/prepare", dependencies=[Depends(authenticate)])
    def prepare(body: PrepareBody):
        try:
            return worker.prepare(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (OSError, RuntimeError, ImportError) as exc:
            raise HTTPException(
                503, f"Could not load the capture model: {exc}"
            ) from exc

    @app.post("/complete", dependencies=[Depends(authenticate)])
    def complete(body: CompleteBody):
        try:
            return worker.complete(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/cancel", dependencies=[Depends(authenticate)])
    def cancel(body: SessionBody):
        return worker.cancel(body)

    @app.get("/result/{session_id}", dependencies=[Depends(authenticate)])
    def result(session_id: str, request_id: str | None = Query(default=None)):
        return worker.result(session_id, request_id)

    @app.post("/release", dependencies=[Depends(authenticate)])
    def release(body: SessionBody):
        return worker.release(body)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8890)
    parser.add_argument(
        "--adapter-root", type=Path, default=Path.home() / ".unsloth/studio/outputs"
    )
    parser.add_argument(
        "--token-file", type=Path, default=os.getenv("GRPO_CAPTURE_TOKEN_FILE")
    )
    args = parser.parse_args()
    if not args.token_file:
        parser.error("--token-file or GRPO_CAPTURE_TOKEN_FILE is required")
    token = args.token_file.read_text(encoding="utf-8-sig").strip()
    import uvicorn

    uvicorn.run(
        create_app(CaptureWorker(args.adapter_root), token),
        host=args.host,
        port=args.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
