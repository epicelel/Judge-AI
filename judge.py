#!/usr/bin/env python3
"""
JudgeAI CLI entry point.

    python judge.py new LD
    python judge.py new my_round.txt
"""

import sys
from pathlib import Path

# Run from a checkout without needing an install step.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.cli import cli  # noqa: E402

if __name__ == "__main__":
    cli()
