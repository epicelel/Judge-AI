#!/usr/bin/env python3
"""JudgeAI CLI entry point."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import load_into_environment  # noqa: E402

load_into_environment()

from src.cli import cli  # noqa: E402


if __name__ == "__main__":
    cli()
