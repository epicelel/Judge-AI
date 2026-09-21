#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -r requirements.txt -r requirements-build.txt
python3 -m pytest tests -q
python3 -m PyInstaller --noconfirm --clean JudgeAI.spec
echo "Build complete. Keep dist/JudgeAI and dist/JudgeAI-CLI together."
