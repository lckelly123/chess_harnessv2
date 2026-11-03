"""CPU-only checks: no Unsloth import, pretrained weights, or optimizer steps."""

import contextlib
import copy
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "GRPO_trainer.py"
spec = importlib.util.spec_from_file_location("grpo_training", SCRIPT)
trainer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = trainer
spec.loader.exec_module(trainer)

try:
    import torch
except ImportError:
    torch = None


def dump_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def dump_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def record(call=1, **overrides):
    return {
        "run_id": "run-one",
        "call_index": call,
        "prompt_token_ids": [1, 2, 3],
        "completion_token_ids": [4, 5],
        "old_logprobs": [-0.2, -2.0],
        "status": "completed",
        "capture_valid": True,
        "finish_reason": "stop",
        "error": None,
        "harness_rejected": False,
        "harness_status": "completed",
        **overrides,
    }


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.adapter = self.root / "adapter"
        self.adapter.mkdir()
        dump_json(
            self.adapter / "adapter_config.json",
            {
                "peft_type": "LORA",
                "base_model_name_or_path": "base/model",
                "bias": "none",
            },
        )
        # Validation never parses/loads the weights; their fingerprint is sufficient.
        (self.adapter / "adapter_model.safetensors").write_bytes(b"fixture weights")
        (self.adapter / "tokenizer.json").write_text("{}", encoding="utf-8")
        self.worker = {
            "base_model": "base/model",
            "base_model_revision": "revision-one",
            "adapter_sha256": trainer.sha256(
                self.adapter / "adapter_model.safetensors"
            ),
            "file_sha256": {
                "tokenizer.json": trainer.sha256(self.adapter / "tokenizer.json")
            },
            "old_logprobs_convention": trainer.RAW_LOGPROBS,
        }
        self.capture = self.root / "capture_config.json"
        self.data = self.root / "trajectory_01.jsonl"
        self.advantages = self.root / "advantages.jsonl"
        dump_json(self.capture, {"capture_worker": self.worker})
        dump_jsonl(self.data, [record(A=0.75)])

    def load(self, advantages=None):
        return trainer.load_data([self.data], advantages, None, 8192)

    def cli(self, *extra):
        return [
            "--adapter-path",
            str(self.adapter),
            "--data",
            str(self.data),
            "--output-dir",
            str(self.root / "new-adapter"),
            *extra,
        ]

    def test_inline_advantage_is_not_derived_from_rejection(self):
        dump_jsonl(self.data, [record(A=-2.75, harness_rejected=False)])
        samples, *_ = self.load()
        self.assertEqual(samples[0].advantage, -2.75)

    def test_sidecar_selects_calls_and_call_overrides_run(self):
        dump_jsonl(self.data, [record(), record(2), record(3, run_id="unselected")])
        dump_jsonl(
            self.advantages,
            [
                {"run_id": "run-one", "A": 0.35},
                {"run_id": "run-one", "call_index": 2, "A": -1.25},
            ],
        )
        samples, _, _, excluded = self.load(trainer.load_advantages(self.advantages))
        self.assertEqual([s.advantage for s in samples], [0.35, -1.25])
        self.assertEqual(excluded, 1)

    def test_repeated_inputs_are_not_implicitly_deduplicated(self):
        dump_jsonl(self.data, [record(A=1), record(2, A=-1)])
        self.assertEqual(len(self.load()[0]), 2)

    def test_harness_failure_is_trainable(self):
        dump_jsonl(
            self.data, [record(A=-1, harness_status="failed", harness_error="bad tags")]
        )
        self.assertEqual(self.load()[0][0].advantage, -1)

    def test_generation_failures_and_bad_token_data_fail_closed(self):
        cases = [
            {"status": "failed"},
            {"capture_valid": False},
            {"error": "CUDA error"},
            {"finish_reason": "length"},
            {"truncated": True},
            {"prompt_truncated": True},
            {"completion_token_ids": []},
            {"prompt_token_ids": [True]},
            {"completion_token_ids": [-1]},
            {"old_logprobs": [-0.2]},
            {"old_logprobs": [float("nan"), -1]},
            {"old_logprobs": [0.1, -1]},
            {"completion_mask": [0, 0]},
            {"completion_mask": [1]},
            {"completion_mask": [1, 2]},
            {"A": True},
            {"A": float("inf")},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                dump_jsonl(self.data, [record(**{"A": -1, **changes})])
                with self.assertRaises(ValueError):
                    self.load()

    def test_no_implicit_truncation(self):
        with self.assertRaisesRegex(ValueError, "never truncate"):
            trainer.load_data([self.data], None, None, 4)

    def test_missing_advantages_and_unmatched_selectors_fail(self):
        dump_jsonl(self.data, [record()])
        with self.assertRaisesRegex(ValueError, "A"):
            self.load()
        with self.assertRaisesRegex(ValueError, "missing calls"):
            self.load({("run-one", 1): 1, ("run-one", 99): -1})

    def test_ambiguous_or_duplicate_advantages_fail(self):
        with self.assertRaisesRegex(ValueError, "inline A"):
            self.load({("run-one", 1): 1})
        dump_jsonl(self.advantages, [{"run_id": "run-one", "A": 1}] * 2)
        with self.assertRaisesRegex(ValueError, "duplicate advantage"):
            trainer.load_advantages(self.advantages)

    def test_duplicate_call_and_data_file_fail(self):
        dump_jsonl(self.data, [record(A=1), record(A=-1)])
        with self.assertRaisesRegex(ValueError, "duplicate model-call"):
            self.load()
        with self.assertRaisesRegex(ValueError, "duplicate data file"):
            trainer.load_data([self.data, self.data], None, None, 8192)

    def test_probability_convention_cannot_silently_change(self):
        self.worker["old_logprobs_convention"] = "sampling_logprobs"
        dump_json(self.capture, {"capture_worker": self.worker})
        with self.assertRaisesRegex(ValueError, "RAW policy"):
            self.load()

    def test_adapter_mismatch_requires_explicit_option(self):
        self.worker["adapter_sha256"] = "a" * 64
        metadata = {self.capture: self.worker}
        with self.assertRaisesRegex(ValueError, "Starting adapter differs"):
            trainer.check_adapter(self.adapter, metadata, False)
        self.assertTrue(
            trainer.check_adapter(self.adapter, metadata, True)["off_policy_start"]
        )

    def test_tokenizer_and_base_mismatch_cannot_be_overridden(self):
        self.worker["base_model"] = "another/model"
        with self.assertRaisesRegex(ValueError, "base model differs"):
            trainer.check_adapter(self.adapter, {self.capture: self.worker}, True)
        self.worker["base_model"] = "base/model"
        (self.adapter / "tokenizer.json").write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, "tokenizer.json differs"):
            trainer.check_adapter(self.adapter, {self.capture: self.worker}, True)

    def test_zero_advantages_require_some_learning_signal(self):
        dump_jsonl(self.data, [record(A=0)])
        with self.assertRaisesRegex(ValueError, "nonzero"):
            self.load()

    def test_output_never_overwrites_input_or_existing_directory(self):
        for output in (self.adapter, self.adapter / "child", self.root):
            with self.subTest(output=output), self.assertRaises(ValueError):
                trainer.check_output(output, self.adapter, [self.data])

    def test_validate_only_does_not_import_gpu_libraries_or_create_output(self):
        # A separate interpreter starts without torch, even when this test suite
        # uses torch for tiny CPU loss checks.
        code = (
            "import importlib.util,sys; "
            f"s=importlib.util.spec_from_file_location('t', {str(SCRIPT)!r}); "
            "m=importlib.util.module_from_spec(s); sys.modules['t']=m; "
            "s.loader.exec_module(m); "
            f"assert m.main({self.cli('--validate-only')!r}) == 0; "
            "assert 'torch' not in sys.modules; assert 'unsloth' not in sys.modules"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "new-adapter").exists())

    def test_invalid_cli_settings_fail_before_model_loading(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                trainer.main(self.cli("--learning-rate", "nan", "--validate-only")), 2
            )


@unittest.skipIf(torch is None, "PyTorch is required for CPU loss checks")
class LossTests(unittest.TestCase):
    def loss(self, ratios, advantage, mask=None):
        old = torch.tensor([-3.0] * len(ratios), requires_grad=True)
        current = (old.detach() + torch.tensor(ratios).log()).requires_grad_()
        mask = torch.tensor(mask if mask is not None else [1] * len(ratios))
        loss, metrics = trainer.clipped_policy_loss(current, old, advantage, mask, 0.2)
        loss.backward()
        return loss.item(), current.grad, old.grad, metrics

    def test_positive_advantage_increases_probability_and_clips_only_upper_side(self):
        loss, grad, old_grad, metrics = self.loss([0.5, 1, 1.5], 1)
        self.assertAlmostEqual(loss, -(0.5 + 1 + 1.2) / 3, places=6)
        self.assertTrue(torch.allclose(grad, torch.tensor([-0.5 / 3, -1 / 3, 0.0])))
        self.assertIsNone(old_grad)
        self.assertAlmostEqual(metrics["clip_fraction"], 1 / 3, places=6)

    def test_negative_advantage_decreases_probability_and_clips_only_lower_side(self):
        loss, grad, old_grad, _ = self.loss([0.5, 1, 1.5], -1)
        self.assertAlmostEqual(loss, (0.8 + 1 + 1.5) / 3, places=6)
        self.assertTrue(torch.allclose(grad, torch.tensor([0.0, 1 / 3, 1.5 / 3])))
        self.assertIsNone(old_grad)

    def test_supplied_continuous_advantage_and_token_mask(self):
        loss, grad, _, _ = self.loss([1, 1, 1], -2.5, mask=[1, 0, 1])
        self.assertEqual(loss, 2.5)
        self.assertTrue(torch.equal(grad, torch.tensor([1.25, 0, 1.25])))

    def test_zero_advantage_has_no_gradient(self):
        loss, grad, _, _ = self.loss([0.5, 1, 1.5], 0)
        self.assertEqual(loss, 0)
        self.assertEqual(grad.abs().sum().item(), 0)

    def test_checkpointed_head_matches_dense_logprobs_and_gradients(self):
        class TinyModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embedding = torch.nn.Embedding(11, 7)
                self.head = torch.nn.Linear(7, 11, bias=False)

            def get_output_embeddings(self):
                return self.head

            def forward(self, input_ids, **kwargs):
                self.input_ids = input_ids.detach().tolist()
                self.kwargs = kwargs
                hidden = self.embedding(input_ids)
                return SimpleNamespace(logits=hidden[:, -kwargs["logits_to_keep"] :])

        torch.manual_seed(12)
        model = TinyModel()
        dense = copy.deepcopy(model)
        sample = trainer.Sample(
            ("r", 1), [1, 2, 3], [4, 5, 6], [-3] * 3, [1] * 3, -1, "fixture"
        )
        actual = trainer.completion_logprobs(model, sample, "cpu", 2, lambda x: x)
        # Prompt's final token predicts completion[0]; completion[-2] predicts EOS.
        hidden = dense.embedding(torch.tensor([[1, 2, 3, 4, 5]]))[0, 2:]
        expected = (
            dense.head(hidden)
            .log_softmax(-1)
            .gather(1, torch.tensor([[4], [5], [6]]))
            .squeeze(1)
        )
        self.assertTrue(torch.allclose(actual, expected, atol=1e-6))
        actual.sum().backward()
        expected.sum().backward()
        self.assertTrue(
            torch.allclose(model.head.weight.grad, dense.head.weight.grad, atol=1e-6)
        )
        self.assertTrue(
            torch.allclose(
                model.embedding.weight.grad, dense.embedding.weight.grad, atol=1e-6
            )
        )
        self.assertEqual(model.input_ids, [[1, 2, 3, 4, 5]])
        self.assertFalse(model.kwargs["use_cache"])
        self.assertEqual(model.kwargs["position_ids"].tolist(), [[0, 1, 2, 3, 4]])


if __name__ == "__main__":
    unittest.main()
