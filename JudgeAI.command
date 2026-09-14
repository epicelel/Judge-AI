#!/bin/bash
# JudgeAI Launcher for macOS
# Double-click to launch the GUI app

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Activate virtual environment
source .venv/bin/activate

# Launch GUI
python gui_app.py

# Keep terminal open if there's an error
if [ $? -ne 0 ]; then
    echo ""
    echo "Press Enter to close..."
    read
fi
