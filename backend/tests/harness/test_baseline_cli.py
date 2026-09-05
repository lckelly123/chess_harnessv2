import json
import os
import subprocess
import sys
from pathlib import Path


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "harness.baseline", *args],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
            "LMSTUDIO_MODEL": "",
        },
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_demo_runs_without_local_model_or_credentials():
    result = run_cli("--demo")
    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)
    assert decision["move"]["san"] == "e4"
    assert decision["defense_report"] is None
    assert decision["attack_report"] is None


def test_diagram_uses_actual_two_node_graph_without_model():
    result = run_cli("--diagram")
    assert result.returncode == 0, result.stderr
    assert "decide" in result.stdout
    assert "validate_submission" in result.stdout
    assert "defense" not in result.stdout
    assert "synthesis" not in result.stdout


def test_demo_does_not_pretend_to_support_arbitrary_positions():
    result = run_cli("--demo", "--fen", "4k3/1P6/8/8/8/8/8/4K3 w - - 0 1")
    assert result.returncode != 0
    assert "starting position only" in result.stderr


def test_live_mode_requires_model_setting():
    result = run_cli()
    assert result.returncode != 0
    assert "LMSTUDIO_MODEL" in result.stderr
