# JudgeAI Quick Setup Guide

JudgeAI v0.1 currently supports Lincoln-Douglas (LD) transcripts.

## 1. Install

JudgeAI requires Python 3.12 or newer.

### macOS

```bash
cd ~/Desktop/Judge-AI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python gui_app.py
```

After the first setup, you can also make the included launcher executable:

```bash
chmod +x JudgeAI.command
```

Then double-click `JudgeAI.command` in Finder. The repository does **not**
contain a packaged `JudgeAI.app`.

### Windows

From PowerShell inside the repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe gui_app.py
```

Using the virtual environment's Python directly works even when PowerShell
script execution blocks `Activate.ps1`.

## 2. Add an API key

Open **Settings** in the desktop app and choose either:

- OpenAI API
- Anthropic API
- Auto-detect, if you have both configured

Paste the corresponding API key and click **Save**.

Saved keys are stored locally in plaintext at:

```text
~/.judgeai/config.json
```

On macOS/Linux, JudgeAI applies private file permissions where supported.
Environment variables can be used instead if you do not want the key stored
in this file. Never commit API keys.

OpenAI keys: https://platform.openai.com/api-keys
Anthropic keys: https://console.anthropic.com/

## 3. Judge a round

In the desktop GUI, drop a `.txt` or `.rtf` LD transcript onto the window.

The canonical command-line equivalent is:

```bash
python judge.py new /path/to/transcript.txt --yes
```

The default is three runs per paradigm. For a cheaper first live test:

```bash
python judge.py new /path/to/transcript.txt --yes --runs 1
```

For an offline preview with no model calls:

```bash
python judge.py new /path/to/transcript.txt --yes --runs 1 --dry-run
```

Results are saved under:

```text
~/Desktop/JudgeAI/Ballots/
```

## Providers and fallback

When **Auto-detect** is selected:

- one configured API key -> JudgeAI uses that provider
- both Anthropic and OpenAI keys -> JudgeAI can fall back between them
- no API key -> JudgeAI reports that no provider is configured

AWS Bedrock is still available only when explicitly selected/configured in
code or through `LLM_PROVIDER=bedrock`; it is not part of the automatic
Anthropic/OpenAI fallback chain.

## Costs

Model calls can incur charges, and provider pricing can change. JudgeAI shows
estimated token usage/cost after a run, but always check the model provider's
current pricing before relying on those estimates.

## Testing

Run the offline test suite with:

```bash
python -m pytest tests -q
```

If you changed dependencies, reinstall them before testing:

```bash
python -m pip install -r requirements.txt
```
