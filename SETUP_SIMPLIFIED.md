# JudgeAI v0.9 — Simple Setup

## Windows

```powershell
git clone https://github.com/epicelel/Judge-AI.git
cd Judge-AI
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe gui_app.py
```

Open **Settings**, select OpenAI or Anthropic, paste the API key, and save.

Drop a `.txt` or `.rtf` LD transcript into the app. JudgeAI will show a review screen before any paid model calls so the resolution, names, paradigms, and run count can be corrected.

## Test the install

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Build a Windows desktop executable

```powershell
build_windows.bat
```

The finished GUI and CLI helper will be in `dist\`.
