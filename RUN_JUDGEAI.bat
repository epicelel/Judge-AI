@echo off
setlocal
cd /d "%~dp0"

title JudgeAI

if exist ".venv\Scripts\python.exe" goto CHECK_DEPS

echo.
echo JudgeAI first-time setup
echo ------------------------
echo Creating a private Python environment for JudgeAI...
echo.

where py >nul 2>nul
if not errorlevel 1 goto USE_PY

where python >nul 2>nul
if errorlevel 1 goto NO_PYTHON

python -m venv .venv
goto CHECK_CREATED

:USE_PY
py -3 -m venv .venv

:CHECK_CREATED
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo JudgeAI could not create its Python environment.
    pause
    exit /b 1
)

echo Installing JudgeAI dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto INSTALL_FAILED
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto INSTALL_FAILED

:CHECK_DEPS
".venv\Scripts\python.exe" -c "import PyQt6, openai, anthropic, click, yaml" >nul 2>nul
if errorlevel 1 (
    echo Updating JudgeAI dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto INSTALL_FAILED
)

echo Starting JudgeAI...
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" gui_app.py
) else (
    start "" ".venv\Scripts\python.exe" gui_app.py
)
exit /b 0

:NO_PYTHON
echo.
echo Python was not found.
echo Install Python 3.12 or newer from https://www.python.org/downloads/
echo Then double-click RUN_JUDGEAI.bat again.
echo.
pause
exit /b 1

:INSTALL_FAILED
echo.
echo JudgeAI could not install its dependencies.
echo Check your internet connection and try again.
echo.
pause
exit /b 1
