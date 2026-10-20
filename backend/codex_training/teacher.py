"""Versioned teacher instructions, separate from the student's harness prompt."""

import hashlib
from pathlib import Path

TEACHER_PROMPT = Path(__file__).with_name("teacher_prompt.md").read_text("utf-8")
TEACHER_VERSION = "chess-teacher-v2"
TEACHER_SHA256 = hashlib.sha256(TEACHER_PROMPT.encode("utf-8")).hexdigest()
REASONING_TOKEN_LIMIT = 1500


def teacher_metadata():
    return {
        "teacher_prompt_version": TEACHER_VERSION,
        "teacher_prompt_sha256": TEACHER_SHA256,
        "reasoning_token_limit": REASONING_TOKEN_LIMIT,
        "reasoning_limit_enforcement": "prompt",
        "reasoning_origin": "authored_explanation",
    }
