# Baseline: direct submission with LangGraph

This is a standalone one-move harness in `backend/harness/baseline`, ported from
the previous repository's Agent Player 2 (`agent-player-2-direct-submit-v4`).
Its version is **`baseline-direct-submit-langgraph-v1`**: the chess input/tool
behaviour is preserved, but the transport and orchestration deliberately differ.

It does not itself apply moves or own a match. The deterministic match runner now
registers it as a selectable frontend player, validates its result again, and
persists the committed position. LangSmith Studio remains a separate setup.

## Responsibilities and graph

- `graph.py`: registers `decide` and `validate_submission`, and exposes
  `BaselineAgent.choose_move(TurnRequest) -> MoveDecision`.
- `nodes.py`: one model request or one deterministic submission check per node
  invocation. All repeats are visible graph edges, not internal model loops.
- `state.py`: fresh, serializable state for each turn; no shared mutable board,
  scratch stack, reports, credentials, or provider conversation state.
- `config.py`: model selection, version, and bounded execution settings.
- `prompts.py` and `prompt.md`: position packet and stable baseline instructions.
- `tools.py`: the only tool schema, argument checks, and traced submission.
- `__main__.py`: live, demo, model-listing, and Mermaid diagram CLI modes.

The normal route is `START -> decide -> validate_submission -> END`. Missing or
malformed tool output loops from `decide` back to `decide` with a forced-tool
instruction. An illegal SAN move loops from validation back to `decide` with
deterministic rejection feedback. Exhausted limits, provider errors, and
cancellation raise explicit errors; the harness never substitutes a random move.

Shared code lives alongside the agent packages:

- `harness/model.py`: the existing asynchronous LM Studio Responses adapter and
  LangSmith model-call wrapper; provider SDK retries remain disabled.
- `harness/protocol.py`: tagged JSON parsing, common string-field/justification
  checks, stable function schemas, and exact legal-SAN validation.
- `harness/prompting.py`: the common text-tool protocol, history formatting, and
  forced-retry context. Agent Player 1's existing prompt-parity tests still cover
  these extracted helpers.
- `harness/contracts.py`: the same turn input/result contract for both agents.
  Defense/attack reports are now optional and are `null` for baseline results.

Baseline does not import Agent Player 1 internals. Each graph invocation starts
with isolated state, so callers can reuse a compiled graph for independent turns.
Concurrent turns must not share or mutate a canonical game board. Callers must
revalidate and commit moves sequentially; the current UI match runner provides
that boundary and permits one active match by default.

## Inputs and output

The dynamic packet retains the old baseline's game ID, player/side to move, FEN,
PGN, last move, canonical legal SAN list (in the original order), game status,
unused scratchboard section, rejected-tool history, and protocol correction.
It does not add tactical scans, SEE results, square inspection, an engine, or
reports from Agent Player 1.

The only tool is `submit_move`, with exactly two required string arguments:
`move` and `justification`. SAN is validated against the real canonical position,
not merely parsed as a move string. UCI and null moves are rejected. The returned
`MoveDecision` includes a normalized internal SAN/UCI move identity and public
justification, but no provider credentials or usage data.

The old request carried move-history objects. V2 derives Last Move from the
supplied PGN instead. A nonempty record must contain one valid game whose final
FEN matches the supplied canonical FEN; inconsistent records fail before inference.
For a position-only request, use `pgn="*"`; Last Move is then `None.`. Custom
starting positions need SetUp/FEN headers when supplying an actual PGN record.

Game-status fields retain the legacy FEN-snapshot behaviour. They cannot establish
repetition draws from history. Even when a position has legal moves, a match
runner must check termination/draw policy before requesting another move.

## Intentional migration differences

- Native function calling is replaced with v2's text-tool interface. Each response
  ends with exactly one `<agent_tool_call>` JSON block containing `tool` and
  `arguments`. No native `tools`, conversation ID, or `previous_response_id` is
  sent. Requests use `store=False`.
- Stable Available Actions instructions move out of the dynamic position packet
  into the developer prompt. The remaining packet and the submit schema are
  compared with fixtures captured from the old repository's actual builders.
- A pass without a usable call gets previous provider-exposed output, an explicit
  forced-action instruction, `reasoning_effort=none`, and a 600-token output cap.
  The same configured local model handles ordinary and forced requests. Prompt
  forcing is not an API guarantee of compliance; every submission is validated.
- The ordinary 4,000-token output cap is preserved from the old baseline. This is
  a per-request output cap, not a precisely metered hidden-reasoning budget.
  Agent Player 1 uses 2,000 per ordinary phase pass, so total budgets are not equal.
- Default limits are three forced retries after an initial missing/malformed call,
  failure on the third rejected submission, 20 protocol corrections, 20 total
  model calls per turn, and seven model-facing history events. All applicable
  limits are enforced; a smaller limit can terminate first. The old separate
  reasoning-pass/working-notes loop is not retained.
- Like Agent Player 1, an illegal submission preserves any active forced-retry
  context. History is bounded, while exposed outputs and tool events remain in
  the turn trace. Provider errors are surfaced rather than silently retried.
- Legacy Working Notes were recorded but not rendered in the actual input. V2
  records exposed output and explicitly includes it in forced-retry context.

Adjust limits through `BaselineConfig` in code and bump the version when changing
behaviour for an experiment. No universal phase engine or match supervisor is
needed for this two-node graph.

## Run through Docker

Run these commands from the repository root (`chess_harnessv2`). They create a
temporary backend container and do not start a game or require the frontend.

Scripted smoke run, with neither inference nor trace uploads:

```powershell
docker compose run --build --rm --no-deps -e LANGSMITH_TRACING=false backend python -m harness.baseline --demo
```

The demo performs a reasoning-only pass followed by a forced legal submission
of `e4`. It is a control-flow demonstration, not a real chess model.

Print the actual graph:

```powershell
docker compose run --rm --no-deps -e LANGSMITH_TRACING=false backend python -m harness.baseline --diagram
```

For a live turn, use the same root `.env` configuration as Agent Player 1:

```dotenv
LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1
LMSTUDIO_MODEL=your-exact-served-model-id
LMSTUDIO_API_KEY=lm-studio
LMSTUDIO_REASONING_EFFORT=medium
LMSTUDIO_RETRY_REASONING_EFFORT=none
```

The standalone command requires `LMSTUDIO_MODEL`. UI-started matches may leave it
blank: the match catalog selects the only currently loaded model and rejects an
ambiguous loaded set.

Load a model and start LM Studio's server. The model/server must support the
configured reasoning settings, including `none` on retries. Use the actual
server token if authentication is enabled; the placeholder above is for an
unauthenticated localhost server. Do not expose the server beyond localhost
without deliberate authentication/firewall configuration.

```powershell
docker compose run --rm --no-deps backend python -m harness.baseline --list-models
docker compose run --rm --no-deps backend python -m harness.baseline
```

`--fen`, `--pgn`, `--game-id`, and `--ply` support other positions/trace labels.
`--demo` supports the starting position only. Live inference may use substantial
local compute. Docker needs no new dependencies, image, ports, or frontend
environment variables: its existing harness copy/mount includes this package.

When running Python directly on Windows, use `http://127.0.0.1:1234/v1` instead.
The CLI reads process environment variables; only Docker Compose automatically
loads the root `.env` in these instructions.

## LangSmith

Both harnesses use the same tracing settings:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your-local-secret
LANGSMITH_PROJECT=chess-harness-v2-dev
```

Keep credentials in the ignored `.env`, never graph state or frontend variables.
Use your account's endpoint/workspace settings where needed. Enabling hosted
tracing uploads recorded positions, PGN, prompts, exposed model output, and tool
results to LangSmith. To trace the scripted demo, omit the command-line
`LANGSMITH_TRACING=false` override; the demo still has no real LLM-call spans.

The root run is `baseline_turn`, with nested `decide`, `validate_submission`,
LM Studio request, and `submit_move` spans. Forced model requests are named
`LM Studio forced tool retry`. Metadata includes `harness=baseline`, its version,
model, game ID, ply, and side. Both agents now also set `thread_id=game_id` for
LangSmith game grouping, propagated to child spans. Use distinct game IDs for
unrelated runs; these labels do not create persistent graph state or a match DB.

Tracing projects can contain both graphs' executions. LangSmith Studio is a
separate setup requiring a local Agent Server and graph registration; neither
this baseline nor `--diagram` installs/configures Studio. Later, both graphs can
be registered on one local server. Dataset evaluation and head-to-head match
orchestration remain separate future work.

## Verification

The offline suite uses scripted models and mocked HTTP/trace clients. It checks
packet/schema parity across ten legacy cases, routing and both retry types,
SAN/argument validation, limits, cancellation, turn isolation/concurrency, shared
project metadata, nested LLM/tool spans, and CLI demo/diagram behaviour. Ordinary
tests do not depend on the old repo, LM Studio, or a LangSmith account.

`tests/harness/capture_legacy_baseline.py` is a one-off fixture generator requiring
the old `backend/shared/src` on PYTHONPATH. It prints JSON from legacy builders;
it does not execute inference or write to the old repository.

```powershell
docker build --target test -t chess-harness-v2-agent-test ./backend
docker run --rm --network none chess-harness-v2-agent-test
docker run --rm --network none chess-harness-v2-agent-test ruff check harness tests/harness
docker run --rm --network none chess-harness-v2-agent-test ruff format --check harness tests/harness
```

Offline tests establish harness mechanics and instrumentation, not whether a
particular local model makes good moves or follows the protocol reliably. That
requires a live smoke run and subsequent controlled comparisons.
