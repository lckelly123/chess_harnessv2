# Fixed-advantage training

`models/GRPO_trainer.py` updates an existing QLoRA adapter with fixed per-call
advantages and a clipped token probability-ratio loss. It uses Unsloth for model
loading and gradient checkpointing. `models/GRPO_rewards.py` supplies advantages
from batch-relative CP loss when the dataset has no A values. Supplied inline A
or an explicit `--advantages` file still takes precedence. There is no reference
model, critic, KL term, response generation, or automatic deduplication.

This is the requested offline experiment, rather than standard online GRPO.
The old policy stays fixed in the recorded log probabilities. The current
policy changes as the supplied adapter is updated. The starting adapter
normally matches the collection checkpoint; `--allow-adapter-mismatch` allows
an intentional later starting checkpoint without changing the old probabilities.
The tokenizer and pinned base model must still match.

## Terminal prompts

Launch the file with the Unsloth Studio Python environment:

```powershell
& "$env:USERPROFILE\.unsloth\studio\unsloth_studio\Scripts\python.exe" `
  .\models\GRPO_trainer.py
```

Without arguments it selects the prepared
`models/training_data/RL_testing/middlegame_move20_v2/training_setv2_grpo.jsonl`
(relative to the script, independent of the working directory) and reads the
starting adapter path from the matching capture metadata. It asks:

```text
New policy name:
Epochs [1]:
Clipping [0.2]:
No. calls gradient accum [8]:
```

Enter a new name; Enter accepts each numeric default. Invalid names/settings
are prompted again. The result is saved to `<starting adapter's parent>/<new
policy name>`, a separate directory beside the old adapter in Studio's outputs
folder. Existing directories cannot be overwritten. Training starts after
these inputs pass validation. Ctrl+C or end-of-input cancels the prompts.

`--adapter-path` and `--data` override the starting checkpoint and dataset. For
unattended use supply `--non-interactive --policy-name NAME` plus any numeric
settings. An explicit `--output-dir` also skips the prompts, preserving the
original command-line workflow. `--validate-only` never prompts and does not
require a new policy name or output directory.

The terminal reports the active example, examples completed out of the current
epoch, completed weight updates, and saving progress. For example:

```text
Epoch 1/2 | completed 7/295 examples | processing example 8/295 | weight updates: 0
Epoch 1/2 | completed 8/295 examples | weight updates: 0 | backpropagation complete; accumulation 8/8
Epoch 1/2 | completed 8/295 examples | weight updates: 1 | weight update 1 applied; ...
```

## Inputs

- `--adapter-path`: local directory containing `adapter_config.json`,
  `adapter_model.safetensors`, and the captured tokenizer files. Defaults to
  the path recorded in the data's capture metadata.
- `--data`: one or more collection directories or JSONL files. Collection
  directories select `trajectory_*.jsonl` files only.
- `--advantages`: JSONL containing externally calculated A values. This file
  also selects which calls enter training. Omitted calls are excluded.
- `--harness-penalty`: deduction for a harness-rejected call when the CP-loss
  helper is used; defaults to `2.0`. Does not alter supplied A values.
- `--policy-name`: new adapter folder name beside the starting adapter, supplied
  interactively by default. `--output-dir` is an alternative explicit location.
- Original `capture_config.json` alongside each data file. If preparing or
  relocating one collection's data, supply its original `--capture-config`.

Each selected capture must have `run_id`, `call_index`, exact
`prompt_token_ids`, `completion_token_ids`, aligned `old_logprobs`,
`capture_valid: true`, `status: "completed"`, and a normal `stop`/`eos` finish.
Generation errors and truncated captures are rejected. A harness-rejected
response, including the final failed call in a trajectory, is still a valid
training sample when its generation finished normally.

An optional `completion_mask` contains one integer 0/1 per generated token;
otherwise every generated token, including EOS, is included. Prompt tokens
never receive loss. Text is retained in source records for inspection but is
not retokenized or used to reconstruct the training sequence.

## Default CP-loss reward helper

When there is no inline A and no `--advantages`, the trainer calls
`GRPO_rewards.supply_advantages()`. For each collection it reads the original
`manifest.json` and binds its trajectory numbers to the run IDs in the original
`trajectory_*.jsonl` files. Keep these files beside the prepared dataset, or
beside `--capture-config` if the prepared data was relocated.

The helper uses **every trajectory in the collection** to determine the batch
range, regardless of how many calls each run has or which calls survive
deduplication. For completed runs, effective loss is the final CP loss; for
failed runs, it is the worst completed run's CP loss. It then calculates:

```text
B_run = 1 - 2 * (effective_cp_loss - batch_min) / (batch_max - batch_min)
A_call = clip(B_run - 2.0 * harness_rejected, -1, 1)
```

Equal losses give `B_run = 0`. A batch with no completed run or a completed run
without a finite CP loss fails validation because its engine baseline is
undefined. Each selected call needs a boolean `harness_rejected` label. No
reward or token fields in the dataset are rewritten.

The same call's A is applied to all its active generated tokens. There is no
further centering or normalization inside an epoch or gradient accumulation
group. With the default penalty of 2, every harness-rejected call clamps to
`-1`, even in the best run. Accepted calls retain their trajectory score. Supplied A values
are accepted unchanged; partially populated inline A fields are an error.

The validation console reports the reward source, penalty, range, and counts
of positive/negative/zero calls. When training is explicitly launched, its
`training_run.json` records the reward formula, batch scores, source hashes,
helper hash, and exact `per_call_advantages` used.

## Supplying A from another reward function

Per-call JSONL entries use the recorded `run_id` and `call_index`:

```jsonl
{"run_id":"YOUR-RUN-UUID","call_index":1,"A":1.0}
{"run_id":"YOUR-RUN-UUID","call_index":2,"A":-1.0}
```

To apply a trajectory-level advantage to every call, omit `call_index`:

```jsonl
{"run_id":"YOUR-RUN-UUID","A":0.72}
```

A per-call entry overrides the run-level entry. Every selector must match a
record. Duplicate selectors and ambiguous inline/sidecar values are errors.
To count only one failed attempt for an identical input, include only that
call's selector: the trainer does not infer failure labels or deduplicate.

Alternatively, add numeric `"A"` directly to every row in a prepared JSONL
and omit `--advantages`. Any finite numeric A is supported, including zero;
zero produces no policy gradient. At least one selected A must be nonzero.
No centering, scaling, clipping, or sign conversion is applied to supplied A.

## Validate without training

For the prepared v2 dataset and default helper, this is sufficient:

```powershell
& "$env:USERPROFILE\.unsloth\studio\unsloth_studio\Scripts\python.exe" `
  .\models\GRPO_trainer.py --validate-only
```

For a different collection, run from the project root and replace the
advantages filename with your own file. This example also includes
`--validate-only`:

```powershell
& "$env:USERPROFILE\.unsloth\studio\unsloth_studio\Scripts\python.exe" `
  .\models\GRPO_trainer.py `
  --adapter-path "$env:USERPROFILE\.unsloth\studio\outputs\Qwen_Qwen3-14B__project-true_trial_v1.2_1792812112" `
  --data .\models\training_data\RL_testing\middlegame_move20 `
  --advantages .\models\training_data\RL_testing\middlegame_move20\advantages.jsonl `
  --output-dir .\models\harness_rl_v1 `
  --validate-only
```

Validation imports no GPU libraries, loads no weights, updates nothing, and
creates no output directory. It checks capture integrity, A selection, token
alignment, context lengths, adapter/tokenizer fingerprints and base identity.
It does not establish GPU fit or test the actual model forward/backward pass.

Removing `--validate-only` starts training. No training has been started as
part of implementing this script. The runtime uses locally cached base weights
by default; `--allow-download` permits fetching the recorded base revision.
The first version supports dense Qwen3, Qwen2 and Llama adapters on a BF16 CUDA
GPU, updating LoRA A/B matrices only. Existing adapters with trained bias,
extra saved modules, or DoRA are rejected.

## Update and memory behavior

For each generated token, `ratio = exp(current_raw_logp - saved_old_logp)`.
Loss is `-min(ratio*A, clamp(ratio, 1-epsilon, 1+epsilon)*A)`, averaged over
active generated tokens in each call, then equally across calls in the
gradient-accumulation group. The final partial group uses its actual size.
Old probabilities are detached constants. There is no prompt-token loss and
no optimizer state inherited from SFT.

Gradient accumulation controls when **weights are updated**, not when
backpropagation is performed. With accumulation 8, each call runs a forward
pass and backward pass; its gradients are added to the running sum. After
eight calls, the optimizer applies their averaged gradient and clears it.
The calls within a group all see the same current weights. For 295 nonzero-A
calls, one epoch has 295 backward passes and 37 weight updates (the final
update combines seven calls). A=0 examples are counted as processed but skip
forward/backward work; an entirely zero-A group makes no optimizer update.

The capture worker also saved `sampling_logprobs` after temperature, top-k and
top-p. This trainer deliberately uses **raw policy values on both sides** of
the requested ratio. It does not apply importance correction for the filtered
sampling distribution or the user's example selection. Such correction would
be a different objective; these runs should be described as offline clipped
surrogate experiments rather than unbiased on-policy GRPO.

Only one call is on the GPU at a time. Unsloth activation checkpointing and a
checkpointed output projection avoid retaining a full sequence-by-vocabulary
logit tensor. The projection defaults to 64 completion tokens per chunk.
The full call's context still participates in the transformer forward/backward
pass. This is not inference-only VRAM usage, and actual GPU fit is unmeasured.

Defaults: learning rate `5e-6`, clip epsilon `0.2`, one epoch, accumulation `8`,
maximum context `8192`, gradient norm limit `1.0`, AdamW8bit, zero weight decay,
and disabled dropout. Use `--max-steps` to cap optimizer updates, `--optimizer
adamw` for PyTorch AdamW, or `--help` for all options. The script never silently
truncates a saved prompt or completion.

Successful output contains the new adapter and tokenizer, `training_run.json`
(configuration, source fingerprints, supplied-A counts, package versions), and
`metrics.jsonl` (loss, ratios, clipping, gradient norm, peak allocated VRAM).
The output directory must not already exist. The original adapter is preserved.
An interrupted run records failure; this version does not resume optimizer state.

CPU-only tests (no pretrained weights or optimizer updates):

```powershell
& "$env:USERPROFILE\.unsloth\studio\unsloth_studio\Scripts\python.exe" `
  -m unittest discover -s models/tests -p test_grpo_trainer.py
```
