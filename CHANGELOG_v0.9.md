# JudgeAI v0.9

v0.9 is the feature-complete pre-1.0 release.

## Round setup

- Added a pre-judging review dialog before paid API calls
- Zero-cost local detection for explicit resolution and Aff/Neg labels
- Editable resolution, Aff, and Neg fields
- Select any subset of the four LD paradigms
- Select 1, 3, or 5 runs per paradigm
- Added a rough low/high API-cost preview

## Results

- Added an overall paradigm split summary
- Added per-paradigm decision cards
- Kept individual ballot tabs and cross-paradigm analysis
- Added Copy Current Tab
- Added combined Markdown, text, and PDF export
- Added Open Folder and Open Transcript actions
- Added Retry This Paradigm for in-place rejudging and diff regeneration

## History

- Search by round ID, date, resolution, Aff, or Neg
- Filter by debate-format metadata
- Filter by AFF majority, NEG majority, or split/incomplete rounds
- Open a saved round, open its transcript, or delete its saved results from the GUI

## Settings

- Added provider/model controls
- Added configured/not-configured API-key status
- Added default run count
- Added default paradigm selection

## Reliability and UX

- Added cancellable GUI subprocesses
- Added friendly API-key, rate-limit, and connection error messages
- Partial rounds remain visible instead of being discarded
- Individual failed paradigms can be retried without rerunning the whole round
- Packaged builds use a sibling JudgeAI-CLI helper so the GUI and CLI still share one backend

## Judging safeguards

- Added explicit transcript-grounding rules
- Judges may not invent evidence, source names, statistics, concessions, or missing warrants
- Clarified dropped-argument handling
- Clarified CX concession handling
- Clarified final-rebuttal new-argument handling
- Cross-paradigm synthesis must stay within saved ballots

## Packaging

- Added PyInstaller configuration
- Added Windows build scripts
- Added macOS build script
- Added GitHub Actions workflow for Windows and macOS build artifacts

## Version

- CLI and desktop app now identify as JudgeAI v0.9
