# Fixed-advantage training

`models/GRPO_trainer.py` updates an existing QLoRA adapter with supplied
advantages and a clipped token probability-ratio loss. It uses Unsloth for model
loading and gradient checkpointing. There is no reward function, group
normalization, reference model, critic, KL term, response generation, or
automatic deduplication in this script.

This is the requested offline experiment, rather than standard online GRPO.
The old policy stays fixed in the recorded log probabilities. The current
policy changes as the supplied adapter is updated. The starting adapter
normally matches the collection checkpoint; `--allow-adapter-mismatch` allows
an intentional later starting checkpoint without changing the old probabilities.
The tokenizer and pinned base model must still match.

## Inputs

- `--adapter-path`: local directory containing `adapter_config.json`,
  `adapter_model.safetensors`, and the captured tokenizer files.
- `--data`: one or more collection directories or JSONL files. Collection
  directories select `trajectory_*.jsonl` files only.
- `--advantages`: JSONL containing externally calculated A values. This file
  also selects which calls enter training. Omitted calls are excluded.
- `--output-dir`: a new directory for the updated adapter and training records.
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

## Supplying A

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
No centering, scaling, clipping, or sign conversion is applied to A itself.

## Validate without training

Run from the project root. Replace the advantages filename with your own file.
The example deliberately includes `--validate-only`:

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
