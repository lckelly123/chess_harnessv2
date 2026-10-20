# Codex training through the chess harness

**Positional testing → Codex (training) → Run once** runs a saved position with
your signed-in Codex CLI. The existing harness owns the boards, prompt builder,
parser, tools, database passes, final move validation, and subsequent Stockfish
grading. You can also choose **Queue harness → Codex (training)** under **Run a
full set** to process the training or test set. Neither mode automatically exports
a JSONL dataset.

```text
Web UI → backend creates the normal positional run
Windows worker claims it → fresh codex exec process for each pass
Codex → stdio MCP → current harness input and submitted response
Backend → parses response, executes tools, records pass, creates next input
Validated submit_move → engine grading → normal results/history UI
```

## Windows setup

From the repository root, install the adapter dependencies into the existing
backend virtual environment and recreate the backend with its runtime mount:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-mcp.txt
docker compose up -d --no-deps backend
.\scripts\start-codex-worker.ps1
```

Codex must already be installed and signed in (`codex login`). The launcher runs
the worker in the background without opening a terminal window. The UI detects it
automatically. LM Studio and Unsloth do not need to have a model loaded for this
option. Running the launcher again does not start a second worker.

The worker reads the default `model` from your Codex configuration and defaults
to **extra high (`xhigh`) reasoning**, independently of your general Codex effort
setting. Override effort with `-ReasoningEffort` (or `CODEX_TEACHER_REASONING_EFFORT`).
It chooses the newest available native CLI among PATH and
installed desktop binaries, avoiding an outdated PATH executable. It preserves
your global configuration. Override the model at startup if wanted:

```powershell
.\scripts\start-codex-worker.ps1 -Model gpt-6-astra -ReasoningEffort xhigh
```

Overrides apply to a newly started worker, not one already running. To use a
specific executable, set `CODEX_CLI_PATH` before starting. The foreground form is
useful for diagnostics and can be stopped with Ctrl+C:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m codex_training.worker
```

The UI displays the connected worker's model and effort. Those exact values are
passed to `codex exec` and saved in the run's configuration, along with the CLI
version and teacher-prompt hash. This records the requested CLI model; it is not
an independent verification of the remote server's weights.

## Full-set queues

In **Positional testing → Run a full set**, choose the training or test set,
dataset, and **Codex (training)** as the queue harness. Add an optional queue name,
then click **Run full queue**. The connected Windows worker must be idle and
online to start. The shared LM Studio, Unsloth, or OpenAI selector does not apply.

The queue captures the worker's model and reasoning effort when created, along
with its position membership. These settings stay fixed for the queue, including
after a worker restart. Each position gets its own teacher session, with a fresh
`codex exec` process per pass, and uses the pre-created queue run record. Inputs,
explanations, tool results, final moves, and subsequent engine grades appear in
the normal history and live trace views.

Keep the Windows worker running; closing the browser is fine. Positions execute
one at a time. A failed position is retained and the queue continues. If the worker
disconnects, the active attempt fails through the existing watchdog and pending
positions wait for reconnection. A backend restart retains interrupted attempts
as failures and continues unstarted positions; it does not replay a paid attempt.

**Stop after current** finishes the active position and skips remaining positions.
The existing queue item timeout also applies to Codex positions (Docker default
2,700 seconds / 45 minutes per position, configured by
`POSITION_QUEUE_ITEM_TIMEOUT_SECONDS`); a timeout stops the teacher session and
records the failed attempt before moving on. The backend reads this setting at
startup. Changing it requires recreating the backend, which interrupts the active
position and resumes pending positions with the new limit. A standalone backend
without this environment setting retains its 1,800-second fallback.

## Teacher prompt and response format

The source of the instructions is
[`backend/codex_training/teacher_prompt.md`](../backend/codex_training/teacher_prompt.md).
Each pass supplies it alongside the exact harness input. Version `chess-teacher-v2`
asks for an authored first-person working assessment in Qwen's conversational
style: current evidence, uncertainty, and the next useful action, with corrections
grounded in actual returned tool results. It discourages predetermined conclusions,
manufactured hesitation, and formal retrospective explanations. It preserves the
existing Qwen syntax:

```xml
<think>
Authored explanation of the current decision.
</think>

<running_thoughts>
Vulnerabilities: Current findings and open questions.

Opportunities: Current findings or Not assessed.

Synthesis: Current comparison and top-line candidate.
</running_thoughts>

<agent_tool_calls>
[{"tool":"inspect_square","arguments":{"board":"canonical","square":"e4"}}]
</agent_tool_calls>
```

The MCP submission splits that representation into two required strings:

| Field | Contents |
| --- | --- |
| `reasoning_text` | Explanation only, without `<think>` tags. |
| `response` | Complete `<running_thoughts>` and `<agent_tool_calls>` blocks, in order. |

The explanation instruction is **under 1,500 tokens per pass**, with shorter
explanations encouraged. This is prompt guidance, not a tokenizer-enforced cap.
The API rejects empty explanations, `<think>` wrappers, and strings above 16,000
characters; that safety bound is not equivalent to a 1,500-token count.

Both strings are stored verbatim. The explanation is a `reasoning_text` block in
the saved output envelope; the response is an `output_text` block. Only the latter
goes into the existing harness parser. Expand displays both through the existing
exchange viewer. Metadata explicitly marks the explanation as
`authored_explanation`. No private Codex reasoning is extracted or represented as
captured text. A later training export can wrap the explanation in `<think>` and
join it to the response.

## Session isolation and persistence

Each pass gets a fresh `codex exec --ephemeral --ignore-user-config` process in an
empty temporary directory. The worker supplies the selected model/effort, disables
shell tools and web search, and configures only the chess MCP server. It does not
resume a Codex conversation or load repository instructions and unrelated MCP
servers. Tool output limits allow the complete harness packet through.

The child receives a token scoped to its assigned pass. After submission, it can
only see an acknowledgement, not the next pass's input. The worker retains the
run token and starts the next process when the harness is ready. Teacher sessions
receive no engine grades or engine-selected moves. Grading happens after the
harness accepts the final move.

The database stores the exact harness packet, teacher prompt/version/hash,
execution metadata, and submitted fields. This is the **harness exchange**, not
the entire Codex platform prompt. Board state, working notes, and past tool
results carry forward through the harness's normal dynamic input.

The local worker shares an automatically created `.runtime/worker.token` with the
backend through a read-only Docker mount. It is excluded from Git and never sent
to the browser or included in prompts/datasets. Run/pass tokens stay in process
memory and environment variables. The backend itself does not import the MCP SDK.

## Stop and recovery

- **Stop Codex** stops the current investigation and terminates its child process.
  Saved passes remain in normal run history. A validated move already being
  graded may finish grading. Cancelled attempts use the database's existing
  `failed` status, with a specific stop message.
- Reloading the UI reconnects to the active job. One worker and one UI-created
  Codex run are supported at a time. Clicking Run again creates a new run.
- A disconnected worker causes the backend to close its active run after the
  heartbeat timeout. A restarted worker does not silently resume an old pass.
- Use one backend process. Pending sessions are in memory; backend restarts do
  not resume them. On the first subsequent Codex run, interrupted Codex records
  are marked failed while preserving their exchanges and saved moves.
- An identical retry with the same pass ID and both exact strings is acknowledged
  without executing twice. Changing either string for an accepted pass is rejected.
- Malformed harness responses still follow the existing recorded retry path.
  An MCP acknowledgement means receipt, not successful parsing or move acceptance.

Worker startup/errors are in `.runtime/worker.stderr.log`. Per-pass logs under
`.runtime/logs/<run-id>/` contain operational event metadata and a bounded stderr
tail, with known credentials redacted. Structured `error` / `turn.failed` messages
are retained and take priority over stderr warnings in the reported failure.
They do not save private reasoning events or tool payloads. Before failing a run
on a CLI exit, the worker checks the backend's `last_accepted_pass_id`. If that
matches the assigned pass, processing continues without resubmitting it. A
terminal backend outcome is preserved; transport receipt never overrides harness
validation or grading. An unaccepted pass still fails with the actual CLI error.

## Manual MCP clients

The original direct API remains available for development. Start a run with
`POST /api/codex-training/runs` and a body containing `position_id`, optionally
`model_label` and `pass_timeout_seconds`. Supply its returned `run_id` and
`run_token` as `CHESS_RUN_ID` and `CHESS_RUN_TOKEN` to the MCP subprocess:

```toml
[mcp_servers.chess_training]
command = 'C:\Repos\chess_harness_v2\chess_harnessv2\backend\.venv\Scripts\python.exe'
args = ['-m', 'codex_training.mcp_server']
cwd = 'C:\Repos\chess_harness_v2\chess_harnessv2\backend'
env_vars = ['CHESS_RUN_ID', 'CHESS_RUN_TOKEN', 'CHESS_BACKEND_URL']
startup_timeout_sec = 30
tool_timeout_sec = 45

[mcp_servers.chess_training.tools.get_current_pass]
output_token_limit = 64000

[mcp_servers.chess_training.tools.submit_response]
output_token_limit = 64000
```

`CHESS_BACKEND_URL` defaults to `http://127.0.0.1:8000`; only loopback origins are
accepted. Tools are `get_current_pass()` and
`submit_response(pass_id, reasoning_text, response)`. A run-scoped manual client
can continue through successive passes; a worker-created pass-scoped client must
stop after its acknowledgement. The manual model label is caller-provided and
does not verify the external client's selection. Manually closing stdio does not
stop its backend run; use the authenticated `/runs/<run-id>/stop` endpoint or the
pass deadline.

CLI behavior references: [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
and [MCP configuration](https://learn.chatgpt.com/docs/extend/mcp).

## Verification

Tests cover real harness tools and MCP subprocesses, exact field preservation,
pass token isolation, idempotency, worker dispatch/cancellation/disconnection,
CLI selection, parser retries, and grading failures. The PostgreSQL integration
test uses an isolated temporary schema. The live CLI test opts into one real
Codex pass against a temporary test backend, without creating production history.

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest -q tests/positional_testing/test_codex_training.py tests/positional_testing/test_codex_worker.py
# Optional PostgreSQL checks against the local development server:
$env:POSITIONS_INTEGRATION_TEST = '1'
$env:POSITIONS_DB_HOST = '127.0.0.1'
$env:POSITIONS_DB_PORT = '5433'
.\.venv\Scripts\python.exe -m pytest -q tests/positional_testing/test_codex_training.py
# Optional signed-in CLI smoke test:
$env:CODEX_LIVE_SMOKE = '1'
.\.venv\Scripts\python.exe -m pytest -q tests/positional_testing/test_codex_training.py::test_live_codex_exec_one_isolated_pass
```
