"""Authenticated transport to the single-model Windows capture worker."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import httpx2 as httpx

from harness.contracts import HarnessError
from harness.model import unsloth_connection
from harness.recording import current_recorder

from .storage import PROJECT_ROOT, validate_capture


class CaptureUnavailable(RuntimeError):
    pass


class CaptureClient:
    def __init__(self, base_url=None, token_file=None):
        self.base_url = (
            base_url or os.getenv("GRPO_CAPTURE_BASE_URL", "http://127.0.0.1:8890")
        ).rstrip("/")
        self.token_file = Path(
            token_file
            or os.getenv("GRPO_CAPTURE_TOKEN_FILE")
            or PROJECT_ROOT / ".runtime/grpo-capture.token"
        )
        self.http = httpx.AsyncClient(timeout=30, trust_env=False)

    def headers(self):
        try:
            token = self.token_file.read_text(encoding="utf-8-sig").strip()
        except OSError as exc:
            raise CaptureUnavailable(
                "Start scripts/start-grpo-capture.ps1 to enable token capture."
            ) from exc
        if not token:
            raise CaptureUnavailable(
                "The GRPO capture token file is empty. Restart the capture worker."
            )
        return {"Authorization": f"Bearer {token}"}

    async def health(self):
        try:
            self.headers()
            response = await self.http.get(self.base_url + "/health", timeout=3)
            response.raise_for_status()
            return response.json()
        except (OSError, ValueError, httpx.HTTPError, CaptureUnavailable) as exc:
            raise CaptureUnavailable(
                "Start scripts/start-grpo-capture.ps1 to connect the GRPO capture worker."
            ) from exc

    async def post(self, endpoint, body, *, timeout=30):
        try:
            response = await self.http.post(
                self.base_url + endpoint,
                json=body,
                headers=self.headers(),
                timeout=timeout,
            )
            if response.is_error:
                try:
                    detail = response.json().get("detail", "Capture request failed.")
                except ValueError:
                    detail = "Capture request failed."
                raise CaptureUnavailable(str(detail))
            return response.json()
        except httpx.HTTPError as exc:
            raise CaptureUnavailable(
                "Connection to the GRPO capture worker was interrupted."
            ) from exc

    async def inference_defaults(self):
        """Resolve the same defaults used by Studio's Responses -> Chat route.

        Normal harness requests omit sampling and reasoning overrides. Read the
        running server's schema rather than inventing a second capture profile.
        This is API inference configuration, not the Studio chat UI's preferences.
        """
        base_url, key = unsloth_connection()
        studio_url = base_url.rstrip("/").removesuffix("/v1")
        try:
            response = await self.http.get(
                studio_url + "/openapi.json",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
            response.raise_for_status()
            properties = response.json()["components"]["schemas"][
                "ChatCompletionRequest"
            ]["properties"]
            sampling = {
                name: properties[name]["default"]
                for name in (
                    "temperature",
                    "top_p",
                    "top_k",
                    "min_p",
                    "repetition_penalty",
                )
            }
            sampling["enable_thinking"] = properties["enable_thinking"].get("default")
            # These controls are not implemented by the capture decoder. Refuse
            # changed server defaults rather than silently collect another policy.
            for name, expected in (
                ("presence_penalty", 0),
                ("frequency_penalty", 0),
                ("logit_bias", None),
                ("stop", None),
                ("reasoning_effort", None),
            ):
                if properties[name].get("default") != expected:
                    raise ValueError(f"Unsupported Studio default for {name}.")
            return sampling
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise CaptureUnavailable(
                "Could not resolve Unsloth Studio's default inference settings. "
                "Keep Studio running; no capture-specific defaults will be substituted."
            ) from exc

    async def prepare(self, model_name, session_id, sampling):
        return await self.post(
            "/prepare",
            {
                "model_name": model_name,
                "session_id": session_id,
                "max_seq_length": 8192,
                "sampling": sampling,
                "sampling_source": "unsloth_studio_openapi_chat_completion_defaults",
            },
            timeout=600,
        )

    async def complete(self, session_id, request, seed, timeout_seconds):
        request_id = uuid4().hex
        try:
            return await self.post(
                "/complete",
                {
                    "session_id": session_id,
                    "request_id": request_id,
                    "request": request,
                    "seed": seed,
                    "timeout_seconds": timeout_seconds,
                },
                timeout=timeout_seconds + 60,
            )
        except CaptureUnavailable:
            # Recover a completed/partial reply if the response connection was lost.
            try:
                await self.cancel(session_id)
            except CaptureUnavailable:
                # A lost cancellation response does not imply lost token data.
                pass
            for _ in range(30):
                try:
                    result = await self.http.get(
                        f"{self.base_url}/result/{session_id}",
                        params={"request_id": request_id},
                        headers=self.headers(),
                        timeout=3,
                    )
                    result.raise_for_status()
                    payload = result.json()
                    if payload.get("last_result") is not None:
                        return payload["last_result"]
                    if not payload.get("busy"):
                        break
                except (httpx.HTTPError, ValueError):
                    break
                await asyncio.sleep(1)
            raise

    async def cancel(self, session_id):
        return await self.post("/cancel", {"session_id": session_id}, timeout=10)

    async def release(self, session_id):
        return await self.post("/release", {"session_id": session_id}, timeout=90)

    async def unload_studio(self, model_name):
        base_url, key = unsloth_connection()
        studio_url = base_url.rstrip("/").removesuffix("/v1")
        try:
            response = await self.http.post(
                studio_url + "/api/inference/unload",
                json={"model_path": model_name, "force_cancel_active": False},
                headers={"Authorization": f"Bearer {key}"},
                timeout=60,
            )
        except httpx.ConnectError:
            return  # Studio is closed; the worker still checks available VRAM.
        except httpx.HTTPError as exc:
            raise CaptureUnavailable(
                "Could not release the Studio model before GRPO capture."
            ) from exc
        if response.status_code == 404:
            return  # The model may already have been unloaded.
        if response.is_error:
            raise CaptureUnavailable(
                "Studio could not unload the selected model. Finish active Studio requests and try again."
            )

    async def close(self):
        await self.http.aclose()


class CaptureModel:
    def __init__(self, client, session_id, seed, stopped):
        self.client, self.session_id = client, session_id
        self.seed, self.stopped = seed, stopped
        self.failure = None

    async def complete(
        self,
        *,
        model,
        instructions,
        dynamic_input,
        reasoning_effort,
        max_output_tokens,
        forced_retry,
        native_turn=None,
    ):
        if self.stopped.is_set():
            raise HarnessError("GRPO collection stopped.")
        if native_turn is not None:
            raise HarnessError(
                "GRPO capture currently supports the chess_harness text protocol."
            )
        recorder = current_recorder.get()
        request = {
            "model": model,
            "input": [
                {"role": "developer", "content": instructions},
                {"role": "user", "content": dynamic_input},
            ],
            "max_output_tokens": max_output_tokens,
            "store": False,
        }
        await asyncio.to_thread(recorder.capture_input, request)
        try:
            result = await self.client.complete(
                self.session_id, request, self.seed + recorder.number, 600
            )
            validate_capture(result.get("capture"))
            await asyncio.to_thread(recorder.capture_tokens, result["capture"])
            response = result["response"]
            await asyncio.to_thread(recorder.capture_output, response)
        except (CaptureUnavailable, ValueError, KeyError, TypeError) as exc:
            self.failure = str(exc)
            raise HarnessError(f"GRPO token capture failed: {exc}") from exc
        if result["capture"].get("status") in {"failed", "cancelled", "stopped"}:
            raise HarnessError(
                result["capture"].get("error") or "Generation interrupted."
            )
        return response
