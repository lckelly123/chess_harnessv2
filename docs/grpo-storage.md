# Save for GRPO

**Positional testing → chess_harness → Save for GRPO** collects ten independent
trajectories for the selected position using one frozen QLoRA adapter. Each
trajectory starts with fresh harness state and may contain many model calls.
Trajectories run sequentially. This mode collects training data; it does not
update model weights or calculate group-relative advantages.

Choose the **Unsloth** model provider and the exact saved adapter in the normal
model selector. Enable **Save for GRPO**, enter a new run name such as `XYZ`, and
click **Run 10 trajectories**. The first version supports `chess_harness`
(`agent-player-2-langgraph-v1`). Other providers and harnesses retain their
existing single-run behavior.

## Windows setup

The capture worker uses the Python environment installed with Unsloth Studio.
It runs on Windows beside the Docker backend, so the backend container does not
need CUDA or a second copy of the model. From the project root:

```powershell
.\scripts\start-grpo-capture.ps1
docker compose up -d --build backend
```

Start or recreate the backend only when existing runs are idle. The Compose
configuration mounts `models/training_data/RL_testing` into the backend and
connects to the capture worker at `http://host.docker.internal:8890`.
A native backend defaults to `http://127.0.0.1:8890`; set
`GRPO_CAPTURE_BASE_URL` when using a different worker address.

The launcher creates `.runtime/grpo-capture.token`. The worker requires that
token for preparation, generation, cancellation and release requests; the
browser never receives it. Docker reads it through the existing read-only
runtime mount. Native backends find the same project file automatically or
can override `GRPO_CAPTURE_TOKEN_FILE`. The worker listens on port 8890 for
Docker host access; its health endpoint does not expose the token.

The installed Studio HTTP generation endpoint does not return the required
token-level log probabilities. The capture worker therefore loads the selected
saved adapter through the Unsloth Python library. Starting a collection unloads
the Studio model before preparing the capture worker, avoiding two resident
copies on the GPU. The adapter remains frozen throughout the collection. The
capture worker releases its model when collection ends; reload the adapter in
Studio before returning to ordinary Studio inference.

## Files

A run named `XYZ` writes to the project folder:

```text
models/training_data/RL_testing/XYZ/
    manifest.json
    capture_config.json
    trajectory_01.jsonl
    trajectory_02.jsonl
    ...
    trajectory_10.jsonl
```

Run names are directory names, not arbitrary paths. An existing collection is
never overwritten. The default native output root is the project directory
above; `GRPO_OUTPUT_ROOT` can override it. Docker uses the bind-mounted
`/app/models/training_data/RL_testing` directory so files appear directly in the
project on the host.

`manifest.json` is the live, human-readable summary:

- `position_id`
- `qlora_adapter_version`
- `trajectories`, each containing its number, status, `cp_loss`,
  `rejected_model_calls`, and `tool_counts`

There is no advantage field. CP loss is `null` until a move can be evaluated,
and remains `null` for unevaluable outcomes, including mate scores that cannot
be represented as centipawns. Zero means measured zero CP loss. A rejected
model call is counted once even if it requested several invalid tools. Tool
counts include all parsed model-requested tool calls, including requests in
rejected responses; they are not counts of successful tool execution.

`capture_config.json` contains technical replay metadata: the pinned adapter
and base model identity, tokenizer/chat template identity, harness version,
effective sampling configuration, and probability conventions. These details
do not clutter the manifest.

Before unloading the Studio model, collection reads the running Studio API's
generation defaults from its OpenAPI schema, matching the ordinary harness
Responses request. On the current installation these are temperature `0.6`,
top-p `0.95`, top-k `20`, min-p `0.01`, and repetition penalty `1.0`.
Neither path sends the old fixed `reasoning.effort: medium` parameter. Thinking
is left to the model's chat-template default (enabled for this Qwen3 adapter),
rather than explicitly disabled. Studio chat UI preferences are separate from
these API defaults. Studio must be running so capture can resolve them; it does
not silently fall back to a different profile. Settings, their source, and
independent per-call seeds are saved with the data. Existing collections retain
their original settings and token records.

Each trajectory JSONL file contains one record per finished model call,
including an interrupted call when its partial token capture is available.
Records preserve the readable input, exact input token IDs after formatting
and truncation, original generated text, exact generated token IDs, aligned
old-policy log probabilities, sampler log probabilities, completion reason,
harness rejection details and requested tools. Generated special/end tokens
remain in the token arrays even when ordinary display text would omit them.

The token IDs and probability arrays have the same order and length. The saved
policy probabilities and sampler probabilities have separate fields because
temperature, top-p/top-k and penalties may change the sampling distribution.
The future trainer must use the recorded probability convention consistently.
No parameter gradients, KV caches or full-vocabulary probability tensors are
written to these files.

The capture worker rejects an input that already fills the 8,192-token context
instead of silently changing it. Otherwise it caps new tokens to the remaining
context space and records that effective limit and any resulting cutoff.

## Progress and stopping

The backend owns collection execution; closing or refreshing the page does not
start another collection. The UI reconnects to the active collection and shows
the current trajectory and model-call number.

Each completed call is appended to its trajectory file and the manifest is
updated as harness outcomes become known. Token metadata is collected in CPU
memory during an individual call. A process crash can therefore leave that
in-flight call absent; the already-written calls remain usable.

Failed attempts count toward the ten trajectories and retain their captured
data. **Stop collection** preserves completed trajectories and any available
partial capture, and stops further attempts. This differs from the ordinary
single-run **Cancel run** action, which discards its attempt.

Incomplete collections remain distinguishable from completed ten-trajectory
groups. They should not be silently treated as full GRPO groups by a later
training job.
