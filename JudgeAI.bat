@echo off
REM JudgeAI Launcher for Windows
REM Double-click to launch the GUI app

cd /d "%~dp0"

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Launch GUI
python gui_app.py

REM Keep window open if there's an error
if errorlevel 1 (
    echo.
    echo Press any key to close...
    pause >nul
)
