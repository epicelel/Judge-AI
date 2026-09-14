# JudgeAI

JudgeAI is a Python app for analyzing Lincoln-Douglas debate transcripts from four simulated judge perspectives: lay parent, educated lay, traditional LD, and technical circuit. It produces individual ballots and a comparison of where arguments land across perspectives. These are model-generated assessments, not predictions of a human judge's decision.

## Install

Requires Python 3.12 or newer and access to an Anthropic or OpenAI API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-key-here"  # or OPENAI_API_KEY
python judge.py --help
```

On Windows, activate with `.venv\Scripts\activate` and use `python` in place of `python3`.

For the desktop GUI, run `python gui_app.py`. The command line can judge a transcript with `python judge.py new path/to/round.txt`. The app saves ballots under `~/Desktop/JudgeAI/`.

## Privacy and costs

Transcript text is sent to the configured model provider when judging a round. Model calls can incur charges. Do not submit a transcript unless you have permission to use and share it with that provider. The GUI's saved API-key option writes keys into a local `~/.judgeai/config.json` file; environment variables avoid storing keys there. Never commit that file or real transcripts.

## Development

Run the offline tests with `python -m pytest tests -q`. The private golden-corpus transcripts and their live evaluation tests are excluded from this public source snapshot.

This snapshot has no license grant. Publishing a repository publicly does not by itself grant reuse, modification, or redistribution rights.
