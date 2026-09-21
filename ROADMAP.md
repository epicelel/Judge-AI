# JudgeAI Roadmap

## v0.9 — feature-complete beta

Implemented in this branch/bundle:

- editable pre-judging round review
- paradigm selection
- 1/3/5 runs and cost preview
- improved result summary and individual ballots
- Markdown/text/PDF export
- searchable/filterable history
- delete/open transcript actions
- default runs/paradigms/provider/model settings
- cancellable judging
- friendly provider errors
- individual-paradigm retry
- stronger transcript-grounding rules
- Windows/macOS PyInstaller builds and CI artifacts

## v1.0 — stable public distribution

The remaining work is validation rather than another large feature batch:

- run a larger real-round judging evaluation set
- collect feedback from several external testers
- fix recurring judging failures found by that evaluation
- verify packaged Windows build on clean machines
- verify/sign/notarize macOS build if distributed publicly
- finalize onboarding and screenshots
- create a tagged GitHub release with packaged artifacts

Additional debate formats should be treated as separately validated features rather than assumed extensions of LD.

## v0.9 QoL pass — implemented

- Theme support
- Persistent desktop state
- History sorting, labels, and pins
- API connection test
- Better live progress
- Completion notifications
- Onboarding
- About/version UI
- One-click source launcher on Windows

The remaining setup goal for v1.0 is a tested packaged installer/app so ordinary
users do not need Python, Git, a terminal, or the source tree.
