# JudgeAI v0.9 — Simple Setup

## Windows: easiest source setup

1. Download the JudgeAI repository ZIP (or clone the repository).
2. Open the JudgeAI folder.
3. Double-click:

```text
RUN_JUDGEAI.bat
```

The first launch automatically:

- finds Python 3
- creates `.venv`
- installs `requirements.txt`
- starts the desktop app

Later launches reuse the environment and open JudgeAI directly.

You still need Python 3.12 or newer for this source-based launcher. The v1.0
distribution goal is a packaged Windows app that does not require Python or
command-line setup.

## Manual Windows setup

```powershell
git clone https://github.com/epicelel/Judge-AI.git
cd Judge-AI
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe gui_app.py
```

## First launch

JudgeAI walks through three small steps:

1. choose/configure OpenAI or Anthropic
2. choose default paradigms and 1/3/5 runs
3. upload a `.txt` or `.rtf` LD transcript

Settings also includes a **Test Connection** button that checks provider/model
access without running a debate-judging generation.

User data is stored under:

```text
Documents\JudgeAI
```

## Test the install

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Build a Windows desktop executable

```powershell
build_windows.bat
```

The finished GUI and CLI helper will be in `dist\`.
