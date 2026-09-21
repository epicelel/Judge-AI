# JudgeAI v0.9 Desktop Guide

## Start the app

From source on Windows:

```powershell
.\.venv\Scripts\python.exe gui_app.py
```

## First-time setup

Open **Settings** and:

1. Choose OpenAI API or Anthropic API
2. Enter the API key
3. Optionally override the model ID
4. Choose the default run count
5. Choose the default paradigms
6. Save

## Judge a round

Drop a `.txt` or `.rtf` LD transcript into the app. JudgeAI opens a review screen before any paid calls. Confirm or edit the resolution and participant names, select paradigms, choose 1/3/5 runs, and review the approximate cost range.

## Read results

The result window shows:

- overall paradigm split
- one decision card per paradigm
- Cross-Paradigm tab
- individual judge ballot tabs

Use **Copy Current Tab** or **Export Report** to save the output.

## Retry one paradigm

Open a saved round, switch to the paradigm tab, and click **Retry This Paradigm**. JudgeAI reruns only that paradigm and regenerates the comparison.

## Recent Rounds

Recent Rounds supports search and filters. Select a round to:

- Open results
- Open the saved structured transcript
- Delete the saved round results

## Cancel and errors

While judging or retrying, use **Cancel** to terminate the running backend process. API-key, provider, connection, and rate-limit problems are translated into shorter messages, with raw details available when useful.

## Packaged app

A packaged Windows build contains:

```text
JudgeAI.exe
JudgeAI-CLI.exe
```

Keep both files together. The desktop app uses the CLI helper internally so packaged and source installs share the same judging pipeline.
