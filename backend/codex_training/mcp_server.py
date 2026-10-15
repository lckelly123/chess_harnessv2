"""Run-bound stdio facade. The backend owns all chess state and persistence."""

import argparse
import asyncio
import os
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import PROTOCOL_VERSION

INSTRUCTIONS = """You are connected to one chess_harness run.
Call get_current_pass, then submit_response with that pass_id, reasoning_text,
and your complete visible harness response. Follow the supplied harness and teacher instructions and response
format. Use the harness tools by including them in the response's tool-call block.
Investigate using the returned board state and tool results. Do not look up engine
answers, use external chess tools, or read saved evaluations. reasoning_text is an
authored explanation under 1500 tokens without think tags. response contains only
the running_thoughts and agent_tool_calls blocks. Internal reasoning is not captured.
If status is starting or processing, poll get_current_pass again. A submission is
an acknowledgement of receipt, not proof its tools or final move were accepted.
Continue until the backend returns completed, failed, or cancelled. Only a valid
harness submit_move completes the investigation. An identical submission retry
is safe; never change a response after it has been accepted for that pass_id.
"""


class BackendError(ToolError):
    pass


def create_server(
    client: httpx.AsyncClient, run_id: str, *, pass_id: str | None = None
) -> MCPServer:
    run_id = str(UUID(run_id))
    server = MCPServer(
        "Chess harness",
        instructions=(
            "You are assigned exactly one chess harness pass. Call get_current_pass, "
            "follow its harness and teacher instructions, then submit_response with "
            "reasoning_text and response. After submission is acknowledged, end your "
            "turn immediately. Do not fetch or act on another pass. Use only these "
            "MCP tools; do not read files, run commands, or look up engine answers."
            if pass_id
            else INSTRUCTIONS
        ),
        version=PROTOCOL_VERSION,
        log_level="WARNING",
    )
    prefix = f"/api/codex-training/runs/{run_id}"

    async def request(method, path, **kwargs):
        try:
            response = await client.request(method, prefix + path, **kwargs)
        except httpx.HTTPError as exc:
            raise BackendError(
                "Chess backend could not be reached. Retry the same submission if "
                "its outcome is unknown; do not create a replacement pass."
            ) from exc
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not response.is_success:
            detail = (
                payload.get("detail", "Request rejected.")
                if isinstance(payload, dict)
                else "Request rejected."
            )
            raise BackendError(f"Chess backend HTTP {response.status_code}: {detail}")
        if not isinstance(payload, dict):
            raise BackendError("Chess backend returned an invalid JSON reply.")
        return payload

    @server.tool(
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    async def get_current_pass() -> dict[str, Any]:
        """Get this run's exact harness input, or its processing/terminal status."""
        result = await request("GET", "/pass", params={"wait_seconds": 25})
        if pass_id and result.get("pass") and result["pass"]["pass_id"] != pass_id:
            raise BackendError("This teacher session is assigned to a different pass.")
        return result

    @server.tool(
        structured_output=True,
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def submit_response(
        pass_id: str, reasoning_text: str, response: str
    ) -> dict[str, Any]:
        """Submit the complete visible response verbatim for the given pending pass.

        reasoning_text is an authored explanation under 1500 tokens, without tags.
        response contains only running_thoughts then agent_tool_calls.
        The response must use the supplied harness text format. Returns the next
        input when ready, or processing/terminal status. Identical retries are safe.
        """
        return await request(
            "POST",
            "/response",
            json={
                "pass_id": pass_id,
                "response": response,
                "reasoning_text": reasoning_text,
            },
            params={"wait_seconds": 25},
        )

    return server


async def serve(backend_url: str, run_id: str, token: str, pass_id: str | None = None):
    async with httpx.AsyncClient(
        base_url=backend_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=35,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        await create_server(client, run_id, pass_id=pass_id).run_stdio_async()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=os.getenv("CHESS_RUN_ID"), required=False)
    parser.add_argument(
        "--backend-url",
        default=os.getenv("CHESS_BACKEND_URL", "http://127.0.0.1:8000"),
    )
    args = parser.parse_args()
    try:
        run_id = str(UUID(args.run_id or ""))
    except ValueError:
        parser.error("Set --run-id or CHESS_RUN_ID to a run UUID.")
    token = os.getenv("CHESS_RUN_TOKEN", "")
    if not token:
        parser.error("Set CHESS_RUN_TOKEN to the token returned when creating the run.")
    url = urlparse(args.backend_url)
    if (
        url.scheme not in {"http", "https"}
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username is not None
        or url.password is not None
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        parser.error("The backend URL must be a local loopback HTTP(S) origin.")
    # stdout is reserved exclusively for MCP. argparse and SDK logs use stderr.
    asyncio.run(serve(args.backend_url, run_id, token, os.getenv("CHESS_PASS_ID")))


if __name__ == "__main__":
    main()
