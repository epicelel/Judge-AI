$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

python -m pip install -r requirements.txt -r requirements-build.txt
python -m pytest tests -q
python -m PyInstaller --noconfirm --clean JudgeAI.spec

Write-Host "Build complete: dist\JudgeAI.exe and dist\JudgeAI-CLI.exe"
