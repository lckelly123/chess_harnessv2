"""Reward semantics only: no model, gradients, or GPU dependencies."""

import copy
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from GRPO_rewards import (  # noqa: E402
    advantage_for_pass,
    calculate_advantages,
    trajectory_advantages,
)


def batch():
    return {
        "best": {"status": "completed", "cp_loss": 2},
        "middle": {"status": "completed", "cp_loss": 51},
        "worst": {"status": "completed", "cp_loss": 438},
        "failed": {"status": "failed", "cp_loss": None},
    }


class RewardTests(unittest.TestCase):
    def test_best_worst_and_failed_with_expected_middle_value(self):
        bases = trajectory_advantages(batch())
        self.assertEqual(bases["best"], 1.0)
        self.assertEqual(bases["worst"], -1.0)
        self.assertEqual(bases["failed"], -1.0)
        self.assertAlmostEqual(bases["middle"], 0.7752293577981652)

    def test_penalty_is_per_call_and_clamped_after_subtraction(self):
        bases = trajectory_advantages(batch())
        self.assertEqual(advantage_for_pass(bases["best"], False), 1)
        self.assertEqual(advantage_for_pass(bases["best"], True), -1)
        self.assertEqual(advantage_for_pass(bases["middle"], True), -1)
        self.assertEqual(advantage_for_pass(bases["worst"], True), -1)
        self.assertEqual(advantage_for_pass(bases["failed"], False), -1)
        self.assertEqual(advantage_for_pass(1, True, 0), 1)
        self.assertEqual(advantage_for_pass(1, True, 3), -1)

    def test_every_rejected_call_clamps_to_minus_one(self):
        for base in [-1, -0.5, 0, 0.2, 0.5, 1]:
            with self.subTest(base=base):
                self.assertEqual(advantage_for_pass(base, True), -1)
                self.assertEqual(advantage_for_pass(base, False), base)

    def test_batch_is_not_weighted_by_number_of_model_calls(self):
        calls = [
            {"run_id": "middle", "call_index": i, "harness_rejected": False}
            for i in range(1, 101)
        ]
        original = copy.deepcopy(calls)
        values = calculate_advantages(calls, batch())
        self.assertEqual(len(values), 100)
        self.assertEqual(
            set(values.values()), {trajectory_advantages(batch())["middle"]}
        )
        self.assertEqual(calls, original)

    def test_same_input_receives_separate_labels_for_each_pass(self):
        calls = [
            {
                "run_id": "best",
                "call_index": 1,
                "harness_rejected": True,
                "input": "same",
            },
            {
                "run_id": "best",
                "call_index": 2,
                "harness_rejected": False,
                "input": "same",
            },
        ]
        self.assertEqual(
            calculate_advantages(calls, batch()), {("best", 1): -1, ("best", 2): 1}
        )

    def test_equal_losses_give_zero_base_and_penalty_still_applies(self):
        results = batch()
        for result in results.values():
            if result["status"] == "completed":
                result["cp_loss"] = 20
        self.assertEqual(set(trajectory_advantages(results).values()), {0.0})
        self.assertEqual(advantage_for_pass(0, True), -1)

    def test_failed_run_uses_worst_even_if_it_has_a_stale_numeric_loss(self):
        results = batch()
        results["failed"]["cp_loss"] = 0
        self.assertEqual(trajectory_advantages(results)["failed"], -1)

    def test_missing_or_invalid_engine_baselines_fail_before_training(self):
        cases = [
            {},
            {"failed": {"status": "failed", "cp_loss": None}},
            {"run": {"status": "running", "cp_loss": None}},
            *[
                {"run": {"status": "completed", "cp_loss": value}}
                for value in [None, True, -1, math.nan, math.inf]
            ],
        ]
        for results in cases:
            with self.subTest(results=results), self.assertRaises(ValueError):
                trajectory_advantages(results)

    def test_missing_labels_unknown_run_duplicate_keys_and_bad_penalty_rejected(self):
        valid = {"run_id": "best", "call_index": 1, "harness_rejected": False}
        cases = [
            [dict(valid, run_id="unknown")],
            [dict(valid, call_index=True)],
            [dict(valid, harness_rejected=None)],
            [dict(valid, harness_rejected=1)],
            [valid, valid],
        ]
        for calls in cases:
            with self.subTest(calls=calls), self.assertRaises(ValueError):
                calculate_advantages(calls, batch())
        for penalty in [-1, math.nan, math.inf, True]:
            with self.subTest(penalty=penalty), self.assertRaises(ValueError):
                calculate_advantages([valid], batch(), penalty)


if __name__ == "__main__":
    unittest.main()
