# JudgeAI

JudgeAI is a desktop and command-line tool for analyzing Lincoln-Douglas debate transcripts from four simulated judge perspectives: **Lay Parent, Educated Lay, Traditional LD, and Technical Circuit**. It produces individual ballots plus a cross-paradigm comparison showing where arguments land differently across judge types.

JudgeAI outputs are model-generated assessments. They are not predictions of what a particular human judge will decide.

## Current version

**v0.9** is the feature-complete pre-1.0 release.

### What v0.9 adds

- Round review before paid model calls
  - detected resolution
  - detected Aff and Neg names
  - editable metadata
  - paradigm selection
  - 1, 3, or 5 runs per paradigm
  - approximate cost range before judging
- Improved result viewer
  - overall paradigm split
  - one card per judge type
  - cross-paradigm analysis tab
  - individual ballot tabs
  - copy current tab
  - export combined report as Markdown, text, or PDF
- Better round history
  - search
  - format filtering
  - result filtering
  - open saved transcript
  - delete a saved round
- Retry one paradigm without rerunning the entire round
- Clearer API-key, rate-limit, connection, cancellation, and partial-run messages
- Provider/model settings plus default runs and default paradigms
- Stronger transcript-grounding rules for judging prompts
- Windows/macOS packaging configuration with PyInstaller

### v0.9 quality-of-life pass

- Light, Dark, and Follow System themes
- Restores window size/position and maximized state
- Remembers Recent Rounds search, filters, and sort
- Newest/Oldest/Aff/Neg/Resolution/Result sorting
- Optional display names for saved rounds
- Pin important rounds to the top
- Zero-generation API/model connection test in Settings
- Streaming progress text during the CLI judging pipeline
- Desktop completion notifications when JudgeAI is in the background
- Three-step first-run onboarding
- Version indicator plus About screen
- About screen links to GitHub/Releases and opens the Documents data folder
- One-click `RUN_JUDGEAI.bat` setup/launcher for Windows source users


## Supported debate format

The judging pipeline currently implements **Lincoln-Douglas (LD)**. Historical metadata may contain other debate-format labels, and the history screen can filter those labels, but PF/Worlds/Congress/Parli judging is not yet implemented in the v0.9 desktop workflow.

## Quick start

### Easiest Windows source setup

If you downloaded the repository ZIP or cloned it, double-click:

```text
RUN_JUDGEAI.bat
```

On the first launch it creates a private `.venv`, installs the required Python
packages, and starts JudgeAI. Later launches reuse the same environment.

This still requires Python 3.12 or newer. The v1.0 distribution goal is a
normal packaged desktop download that does not require users to install Python
or work with source code.

### Manual Windows setup

```powershell
git clone https://github.com/epicelel/Judge-AI.git
cd Judge-AI
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe gui_app.py
```

### macOS / Linux

```bash
git clone https://github.com/epicelel/Judge-AI.git
cd Judge-AI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python gui_app.py
```

On first launch JudgeAI shows a short onboarding flow for provider setup,
default paradigms/runs, and the transcript workflow.


## Normal desktop workflow

1. Drop a `.txt` or `.rtf` transcript into JudgeAI.
2. Review the detected resolution and participant names.
3. Correct anything that was detected incorrectly.
4. Choose the judge paradigms and 1, 3, or 5 runs per paradigm.
5. Review the approximate API-cost range.
6. Start judging.
7. Review the overall split, cross-paradigm analysis, and individual ballots.
8. Export or revisit the round from **Recent Rounds**.

JudgeAI keeps user-owned round data separate from the application itself.

On Windows this is normally:

```text
C:\Users\<you>\Documents\JudgeAI\
```

Round artifacts are saved under:

```text
~/Documents/JudgeAI/Ballots/<Round_ID>/
```

If you used an older JudgeAI build that stored data under
`~/Desktop/JudgeAI`, v0.9 imports missing ballots, archived rounds, and inbox
files into the Documents location without deleting the old copies.

Each round can contain:

```text
metadata.json
structured_transcript.md
flow.md
diff.md
judge_lay.md
judge_educated_lay.md
judge_traditional.md
judge_circuit.md
```

## Multi-run judging

JudgeAI can run each paradigm more than once because model judgments can vary between runs.

- **1 run** — fastest and cheapest
- **3 runs** — recommended default
- **5 runs** — more stable, but costs more

A result such as `AFF (2/3) slight lean` means two of three completed runs voted Affirmative. If a run fails or does not produce a parseable ballot, JudgeAI reports that explicitly instead of silently treating it as a dissent.

## Individual paradigm retry

From a saved round, open a paradigm tab and choose **Retry This Paradigm**. JudgeAI reruns only that judge type, replaces its representative ballot, updates the metadata, and regenerates the cross-paradigm analysis.

Retries make additional paid API calls. The saved total cost is cumulative and includes retry calls.

## Exporting

The result viewer can export one combined report containing the cross-paradigm analysis and individual ballots as:

- Markdown (`.md`)
- plain text (`.txt`)
- PDF (`.pdf`)

## CLI

The desktop GUI uses the same canonical backend as the CLI.

```powershell
.\.venv\Scripts\python.exe judge.py --help
```

Judge a round:

```powershell
.\.venv\Scripts\python.exe judge.py new "C:\path\to\round.txt" --yes --runs 3
```

Choose paradigms:

```powershell
.\.venv\Scripts\python.exe judge.py new round.txt --yes --personas lay,traditional,circuit
```

Override detected metadata:

```powershell
.\.venv\Scripts\python.exe judge.py new round.txt --yes --resolution "..." --aff "Name" --neg "Name"
```

Retry one saved paradigm:

```powershell
.\.venv\Scripts\python.exe judge.py retry 123456 --persona circuit --runs 3
```

## Providers and models

JudgeAI supports:

- OpenAI API
- Anthropic API
- AWS Bedrock from the CLI/provider layer

The desktop Settings screen lets users choose OpenAI or Anthropic and optionally override the model ID. Leaving a model field blank uses JudgeAI's provider default.

## Privacy and cost

Transcript text is sent to the configured model provider during judging. Model calls can incur charges. Do not submit a transcript unless you have permission to use it and send it to that provider.

Saved API keys are stored locally in plaintext in `~/.judgeai/config.json` with private file permissions where supported. Environment variables can be used instead if you do not want JudgeAI to persist keys.

Never commit real API keys or private debate transcripts to the repository.

## Development and tests

Run the offline test suite with:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

The public repository excludes private golden-corpus transcripts and live evaluation tests.

## Build the desktop executables

### Windows

```powershell
build_windows.bat
```

or:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

The build produces:

```text
dist/JudgeAI.exe
dist/JudgeAI-CLI.exe
```

Keep the two executables together. `JudgeAI.exe` is the normal desktop app; the GUI uses `JudgeAI-CLI.exe` as its packaged backend helper.

### macOS

```bash
./scripts/build_macos.sh
```

A GitHub Actions workflow in `.github/workflows/build-desktop.yml` can also build Windows and macOS artifacts when run manually or when a version tag is pushed.

## Roadmap to v1.0

v0.9 is intended to be the last large pre-1.0 feature release. The remaining 1.0 work is primarily validation and distribution:

- test judging quality across a larger collection of real rounds
- collect feedback from outside testers
- fix any recurring hallucination or argument-tracking failures found in those tests
- verify Windows packaged builds on clean machines
- verify and sign/notarize a macOS build if distributed publicly
- improve onboarding based on tester feedback
- add additional debate formats only when their judging pipelines are separately validated

## License

This repository currently has **no license grant**. Publishing source publicly does not by itself grant permission to reuse, modify, or redistribute it.
