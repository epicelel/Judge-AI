@echo off
setlocal
cd /d "%~dp0"

echo [1/3] Installing build dependencies...
python -m pip install -r requirements.txt -r requirements-build.txt || exit /b 1

echo [2/3] Running offline tests...
python -m pytest tests -q || exit /b 1

echo [3/3] Building JudgeAI.exe and JudgeAI-CLI.exe...
python -m PyInstaller --noconfirm --clean JudgeAI.spec || exit /b 1

echo.
echo Build complete. Open the dist folder and keep JudgeAI.exe and JudgeAI-CLI.exe together.
echo GUI: dist\JudgeAI.exe
echo CLI: dist\JudgeAI-CLI.exe
endlocal
