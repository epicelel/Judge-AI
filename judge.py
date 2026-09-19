#!/usr/bin/env python3
"""
JudgeAI CLI entry point.

This entry point includes a compatibility shim for older CLI code that still
imports ``BedrockError``. The provider layer now uses ``ModelInvocationError``
instead, so we expose the old name as an alias before importing src.cli.
"""

import sys
from pathlib import Path

# Run from a checkout without needing an install step.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Compatibility for src.cli versions that still import BedrockError.
from src import bedrock_client as _bedrock_client  # noqa: E402
from src.llm_client import ModelInvocationError  # noqa: E402

if not hasattr(_bedrock_client, "BedrockError"):
    _bedrock_client.BedrockError = ModelInvocationError

from src.cli import cli  # noqa: E402


if __name__ == "__main__":
    cli()