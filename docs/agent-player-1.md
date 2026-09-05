# Agent Player 1: local LangGraph harness

This slice implements one move decision. It does not start full games, persist
match history, replace the mock API, or change the frontend.

## Responsibilities

- `backend/harness/agent_player_1/graph.py` registers the six nodes and edges.
- `nodes.py` implements one model pass or one deterministic tool execution.
  There are no internal agent loops: each retry is a graph edge.
- `state.py` owns serializable turn state. Every invocation begins with fresh
  state; clients and credentials live outside it.
- `tools.py` owns schemas, argument checks, report validation, and adapters to
  `chess_core`. Only synthesis can submit a real-position move.
- `prompts.py` assembles the current input from state; `prompts/*.md` contains
  the copied shared contract and three phase instructions.
- `config.py` contains model settings, limits, and the harness/prompt version.
- `backend/harness/model.py` is the LM Studio Responses adapter and model tracing
  boundary. Tests inject a scripted implementation of the same interface.
- `backend/harness/contracts.py` defines the caller's turn input and move output.
- `backend/harness/protocol.py` and `prompting.py` now contain the text-tool
  parsing, common string-argument/SAN checks, history formatting, and retry-prompt
  helpers shared with the independent [baseline](baseline.md). Phase-specific
  tools, prompts, state, and routing stay in this package.

Defense and attack are sequential independent reviews. Attack does not see the
defense report. Synthesis sees both reports, but not earlier scratchboards or
tool histories. A phase transition resets scratch/history/retry counters.
The real position never changes in this graph. A later match runner must
revalidate and commit the returned move and own game termination/history.

The parent graph is the single turn itself, not a graph containing phase
subgraphs. Terminal tool checks execute within the model-pass node and receive
their own trace spans; valid submissions take the edge to the next phase or END.

## LM Studio setup

1. Load the exact model you want to use and start LM Studio's local server.
2. Copy `.env.example` to `.env` at the repository root. Set `LMSTUDIO_MODEL` to
   its exact served identifier. The harness does not select or load a model for you.
3. Docker Desktop uses `http://host.docker.internal:1234/v1` to reach LM Studio
   on the host. For Python running directly on the host, use
   `http://127.0.0.1:1234/v1` instead.
4. If LM Studio requires authentication, set its token in `LMSTUDIO_API_KEY`.
   The `lm-studio` placeholder is for servers with authentication disabled.
5. The chosen model/server must support the configured reasoning settings,
   especially `none` on forced retries. These defaults copy the legacy local
   adapter. An unsupported setting surfaces as an error; it is not silently ignored.

Check Docker-to-host access with a read-only model listing:

```powershell
docker compose run --build --rm --no-deps backend python -m harness.agent_player_1 --list-models
```

If the connection is refused, verify the local server's bind address/port and
Docker Desktop access. Only enable broader network listening deliberately;
use authentication and firewall restrictions if exposing the server beyond localhost.

The local interface uses `/v1/responses` with `store=False`, a developer message
for stable instructions and a user message for the current packet. It does not
use provider conversation IDs or native tool-message history. The OpenAI SDK is
used as a client for LM Studio, not for OpenAI-hosted inference.

Like the legacy LM Studio path, tool schemas are embedded in the prompt. A model
response ends with exactly one `<agent_tool_call>` JSON block containing `tool`
and `arguments`. Native function tools are not sent alongside this text protocol.
The harness validates every parsed argument; a tagged block is not trusted code.

A pass without a usable tool call retries the same phase with the prior exposed
output, a forced-action instruction, reasoning set to `none`, and a 600-token
output limit. Successful tools leave retry mode. The ordinary output cap is
2000 tokens; this is an API output cap, not a separate precisely metered hidden
reasoning budget. No claim is made that a prompt alone guarantees tool compliance.

Run one live decision from the starting position (may use substantial local compute):

```powershell
docker compose run --build --rm --no-deps backend python -m harness.agent_player_1
```

`--fen`, `--pgn`, and `--game-id` can supply another turn. Keep PGN and FEN
consistent; the caller owns the game record. For custom start positions include
the PGN SetUp/FEN headers. A FEN snapshot alone cannot establish repetition draws.

## LangSmith setup

Set these in the root `.env` before creating the backend container:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your-local-secret>
LANGSMITH_PROJECT=chess-harness-v2-dev
```

Set `LANGSMITH_ENDPOINT` for a nondefault region and `LANGSMITH_WORKSPACE_ID` if
required by your account. Compose explicitly forwards this configuration only
to the backend. Credentials are runtime environment variables, not image layers,
frontend variables, graph state, or committed configuration. Do not share the
expanded output of `docker compose config`, which can contain secrets.

Tracing is off by default. Enabling hosted tracing sends the recorded position,
PGN, prompts, exposed model output, reports, and tool results to LangSmith.
Review that data-sharing choice before enabling it.

Each invocation is named `agent_player_1_turn`, with game ID, ply, side, model,
and harness version metadata. `harness=agent_player_1` distinguishes it from the
baseline, and `thread_id=game_id` groups related turn traces (including child
spans) in LangSmith. Use a distinct game ID for unrelated smoke runs. This is
tracing metadata, not a LangGraph checkpointer or persistent game state.
Model calls and tools appear as nested spans;
forced retries have the name `LM Studio forced tool retry`. SDK usage/timing
appears when provided. Only provider-exposed reasoning can be recorded; hidden
internal reasoning is not available. The returned public move decision has no
provider usage/authentication metadata.

Tracing does not provide a match database or restart/resume semantics here.
There is no checkpointer in this slice. Full game records and frontend replay
remain future match-runner work.

## Verification and migration differences

The normal tests run with networking disabled and require neither credentials
nor a loaded model. They test routing, response parsing, scratch isolation,
canonical move validation, per-phase bounds, cancellation, provider errors,
repeat invocations, and nested LangSmith emissions using mocked clients.

`tests/harness/fixtures/legacy_packets.json` was generated from the previous
repository's actual working-tree builders, not handwritten expected output.
Tests compare all tool schemas, static instructions, forced-retry inputs, and
24 dynamic phase packets across eight positions (including check, double check,
en passant, promotion, black to move, and active scratch/history). The helper
`capture_legacy.py` runs only during explicit fixture regeneration, with the
legacy shared package on PYTHONPATH; ordinary tests need no old repository.

Deliberate boundaries/differences from the larger legacy runtime:

- LM Studio is the primary provider; hosted-model and native-tool variants are
  not ported. The configured local model is also used for forced retries.
- Three consecutive forced retries and 80 model calls per phase bound failure
  paths. The legacy defaults of 30 tool calls, three rejected tools, 20 protocol
  retries, and seven history events are retained per phase. The older repository
  instructions mention 15 history entries and a turn-wide rejection limit;
  its current implementation uses seven and resets counters per phase.
- Parsing accepts the documented `tool`/`arguments` shape only, not the legacy
  parser's undocumented alternate envelopes or code-fenced payloads.
- Existing phase formatters did not render Working Notes despite accepting an
  argument for them. That actual input behavior is preserved; exposed output
  is recorded, and the forced retry explicitly receives previous output.
- Scratch depth guidance remains the copied four-halfmove prompt instruction,
  not a new hard-coded search policy.
- The chess core gained the missing checkers/evasions details and now rejects
  null SAN moves that python-chess parses but that are illegal game moves.

Change `prompt_version` when changing the harness or prompts for a new experiment.
Test graph mechanics with scripted responses before comparing model quality.
Passing these tests does not establish that an actual local model follows the
protocol well; that requires a live smoke run and trace inspection.

## References

- [LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangSmith tracing integration](https://docs.langchain.com/langsmith/trace-with-langgraph)
- [LangSmith project configuration](https://docs.langchain.com/langsmith/log-traces-to-project)
- [LM Studio Responses endpoint](https://lmstudio.ai/docs/developer/openai-compat/responses)
- [Official OpenAI function-calling documentation](https://developers.openai.com/api/docs/guides/function-calling)
