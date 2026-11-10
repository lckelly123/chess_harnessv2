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
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "GRPO_trainer.py"
sys.path.insert(0, str(SCRIPT.parent))
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
            "adapter_path": str(self.adapter),
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

    def make_reward_collection(self):
        # The worst completed trajectory is absent from the selected dataset.
        # Its engine score must still set the full batch's normalization range.
        dump_jsonl(self.data, [record(), record(2, harness_rejected=True)])
        dump_jsonl(self.root / "trajectory_02.jsonl", [record(run_id="worst")])
        dump_jsonl(self.root / "trajectory_03.jsonl", [record(run_id="failed")])
        dump_jsonl(self.root / "trajectory_04.jsonl", [record(run_id="middle")])
        dump_json(
            self.root / "manifest.json",
            {
                "trajectories": [
                    {"trajectory": 1, "status": "completed", "cp_loss": 2},
                    {"trajectory": 2, "status": "completed", "cp_loss": 438},
                    {"trajectory": 3, "status": "failed", "cp_loss": None},
                    {"trajectory": 4, "status": "completed", "cp_loss": 51},
                ]
            },
        )
        prepared = self.root / "prepared.jsonl"
        dump_jsonl(
            prepared,
            [
                record(),
                record(2, harness_rejected=True),
                record(run_id="failed"),
                record(run_id="middle"),
            ],
        )
        return prepared

    def test_prepare_supplies_per_pass_rewards_from_full_batch(self):
        prepared = self.make_reward_collection()
        original = prepared.read_bytes()
        args = trainer.configure_run(
            trainer.parser().parse_args(["--data", str(prepared), "--validate-only"])
        )
        samples, _, report = trainer.prepare(args)
        self.assertEqual([s.advantage for s in samples[:3]], [1, -1, -1])
        self.assertAlmostEqual(samples[3].advantage, 0.7752293577981652)
        self.assertEqual(report["reward"]["harness_penalty"], 2.0)
        self.assertEqual(report["reward"]["batches"][0]["max_cp_loss"], 438)
        self.assertEqual(len(report["per_call_advantages"]), 4)
        self.assertEqual(report["per_call_advantages"][1]["A"], -1)
        self.assertEqual(prepared.read_bytes(), original)

    def test_helper_validation_imports_no_gpu_libraries_or_starts_training(self):
        prepared = self.make_reward_collection()
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys; sys.path.insert(0, {str(SCRIPT.parent)!r}); "
                "import GRPO_trainer as t; "
                f"assert t.main(['--data', {str(prepared)!r}, '--validate-only']) == 0; "
                "assert 'torch' not in sys.modules and 'unsloth' not in sys.modules",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"advantage_source": "cp_loss_helper"', result.stdout)

    def test_supplied_advantages_override_helper_and_mixed_inline_is_rejected(self):
        prepared = self.make_reward_collection()
        args = trainer.parser().parse_args(["--data", str(prepared)])
        dump_jsonl(self.advantages, [{"run_id": "run-one", "A": -2}])
        args.advantages = self.advantages
        values, report = trainer.resolve_advantages(args)
        self.assertEqual(values, {("run-one", None): -2})
        self.assertEqual(report["source"], "supplied_sidecar")
        args.advantages = None
        dump_jsonl(prepared, [record(A=3), record(2, A=-3)])
        values, report = trainer.resolve_advantages(args)
        self.assertIsNone(values)
        self.assertEqual(report["source"], "supplied_inline")
        dump_jsonl(prepared, [record(A=3), record(2)])
        with self.assertRaisesRegex(ValueError, "Mixed inline"):
            trainer.resolve_advantages(args)

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
            f"sys.path.insert(0, {str(SCRIPT.parent)!r}); "
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

    def test_interactive_settings_save_beside_previous_adapter(self):
        args = trainer.parser().parse_args(["--data", str(self.data)])
        answers = iter(["policy_v2", "2", "0.15", "4"])
        prompts = []

        def read(prompt):
            prompts.append(prompt)
            return next(answers)

        with contextlib.redirect_stdout(io.StringIO()):
            trainer.configure_run(args, read=read)
        self.assertEqual(args.adapter_path, self.adapter.resolve())
        self.assertEqual(args.output_dir, self.adapter.parent / "policy_v2")
        self.assertEqual(
            (args.epochs, args.clip_epsilon, args.gradient_accumulation_steps),
            (2, 0.15, 4),
        )
        self.assertEqual(len(prompts), 4)
        self.assertTrue(prompts[0].startswith("New policy name"))
        self.assertFalse(args.output_dir.exists())

    def test_interactive_reprompts_for_bad_names_and_numbers(self):
        args = trainer.parser().parse_args(["--data", str(self.data)])
        answers = iter(
            [
                "../escape",
                "adapter",
                "policy_v2",
                "0",
                "2.5",
                "",
                "nan",
                "1.5",
                "",
                "-2",
                "",
            ]
        )
        with contextlib.redirect_stdout(io.StringIO()):
            trainer.configure_run(args, read=lambda _: next(answers))
        self.assertEqual(args.output_dir, self.root / "policy_v2")
        self.assertEqual(
            (args.epochs, args.clip_epsilon, args.gradient_accumulation_steps),
            (1, 0.2, 8),
        )

    def test_policy_names_cannot_escape_or_overwrite(self):
        for name in [
            "",
            ".",
            "..",
            "../escape",
            "C:\\new",
            "a/b",
            "a\\b",
            "NUL",
            "COM1.txt",
            "end.",
            "space ",
            "adapter",
        ]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                trainer.policy_output(self.adapter, name)

    def test_noninteractive_policy_name_never_prompts(self):
        args = trainer.parser().parse_args(
            [
                "--data",
                str(self.data),
                "--policy-name",
                "policy_v2",
                "--non-interactive",
            ]
        )
        trainer.configure_run(args, read=lambda _: self.fail("Unexpected prompt"))
        self.assertEqual(args.output_dir, self.root / "policy_v2")

    def test_validation_needs_no_policy_name_or_terminal(self):
        with (
            patch("builtins.input", side_effect=AssertionError("Unexpected prompt")),
            patch.object(
                trainer, "load_model", side_effect=AssertionError("Model loaded")
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                trainer.main(["--data", str(self.data), "--validate-only"]), 0
            )

    def test_cancelled_prompt_never_starts_training(self):
        with (
            patch("builtins.input", side_effect=EOFError),
            patch.object(trainer, "train") as train,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(trainer.main(["--data", str(self.data)]), 130)
            train.assert_not_called()

    def test_interactive_main_passes_requested_settings_to_trainer(self):
        with (
            patch("builtins.input", side_effect=["new_policy", "3", "0.25", "16"]),
            patch.object(trainer, "train") as train,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(trainer.main(["--data", str(self.data)]), 0)
        args, samples, _, report = train.call_args.args
        self.assertEqual(args.output_dir, self.root / "new_policy")
        self.assertEqual(
            (args.epochs, args.clip_epsilon, args.gradient_accumulation_steps),
            (3, 0.25, 16),
        )
        self.assertEqual(len(samples), 1)
        self.assertEqual(report["settings"]["policy_name"], "new_policy")
        self.assertFalse(args.output_dir.exists())


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


@unittest.skipIf(torch is None, "PyTorch is required for CPU progress checks")
class ProgressTests(unittest.TestCase):
    def simulate(self, advantages, *, epochs=1, max_steps=0):
        """Exercise loop/progress with a scalar CPU graph and a NO-OP optimizer.

        No Unsloth, CUDA, pretrained weights, or parameter updates are involved.
        """
        parameter = torch.tensor(0.0, requires_grad=True)
        gradients = []

        class NoOpOptimizer:
            def __init__(self, *args, **kwargs):
                pass

            def zero_grad(self, **kwargs):
                parameter.grad = None

            def step(self):
                gradients.append(parameter.grad.item())

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "mock-policy"
            args = trainer.parser().parse_args(
                [
                    "--output-dir",
                    str(output),
                    "--optimizer",
                    "adamw",
                    "--gradient-accumulation-steps",
                    "2",
                    "--max-grad-norm",
                    "100",
                    "--epochs",
                    str(epochs),
                    "--max-steps",
                    str(max_steps),
                ]
            )
            model = SimpleNamespace(
                get_input_embeddings=lambda: SimpleNamespace(weight=torch.zeros(10, 2)),
                save_pretrained=lambda path, **kw: dump_json(
                    Path(path) / "adapter_config.json", {}
                ),
            )
            tokenizer = SimpleNamespace(save_pretrained=lambda path: None)
            samples = [
                trainer.validate_sample(record(n + 1), a, "fixture", 8192)
                for n, a in enumerate(advantages)
            ]
            console = io.StringIO()
            report = {}
            with (
                patch.object(
                    trainer,
                    "load_model",
                    return_value=(model, tokenizer, [parameter], None),
                ),
                patch.object(
                    trainer,
                    "completion_logprobs",
                    side_effect=lambda model, sample, *a: (
                        parameter + torch.tensor(sample.old_logprobs)
                    ),
                ),
                patch.object(torch.optim, "AdamW", NoOpOptimizer),
                patch.object(
                    torch, "autocast", side_effect=lambda **kw: contextlib.nullcontext()
                ),
                patch.object(torch.cuda, "max_memory_allocated", return_value=0),
                patch.object(
                    trainer.random.Random, "shuffle", lambda self, values: None
                ),
                contextlib.redirect_stdout(console),
            ):
                trainer.train(args, samples, {}, report)
            metrics = [
                json.loads(line)
                for line in (output / "metrics.jsonl").read_text().splitlines()
            ]
            self.assertEqual(parameter.item(), 0.0)
            return console.getvalue(), gradients, metrics

    def test_progress_and_partial_accumulation_group(self):
        console, gradients, metrics = self.simulate([1, 1, -1])
        self.assertEqual(gradients, [-1.0, 1.0])
        self.assertIn("processing example 3/3", console)
        self.assertIn("Epoch 1/1 | completed 3/3 examples | weight updates: 2", console)
        self.assertEqual([row["examples_completed"] for row in metrics], [2, 3])
        self.assertEqual([row["calls"] for row in metrics], [2, 1])

    def test_zero_advantage_calls_count_as_processed_without_weight_updates(self):
        console, gradients, metrics = self.simulate([0, 0, 1])
        self.assertEqual(gradients, [-1.0])
        self.assertIn("completed 2/3 examples | weight updates: 0 | A=0", console)
        self.assertEqual(metrics[0]["examples_completed"], 3)

    def test_progress_resets_for_each_epoch_and_respects_step_cap(self):
        console, gradients, _ = self.simulate([1, 1, -1], epochs=2)
        self.assertIn("Epoch 2/2 | completed 0/3 examples | weight updates: 2", console)
        self.assertEqual(len(gradients), 4)
        console, gradients, metrics = self.simulate([1, 1, -1], max_steps=1)
        self.assertNotIn("processing example 3/3", console)
        self.assertEqual(len(gradients), 1)
        self.assertEqual(metrics[0]["examples_completed"], 2)


if __name__ == "__main__":
    unittest.main()
