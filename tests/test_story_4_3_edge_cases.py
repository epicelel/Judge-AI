"""
Story 4.3 — the diff handles non-standard rounds cleanly.

(a) blowout — covered in test_story_4_1_diff (the all-agree line).
(b) one paradigm failed — shows `[FAILED — no ballot]`, excluded from win/lose.
(c) >= 3 of 4 failed — the diff is skipped with a graceful error.
"""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.judging import (  # noqa: E402
    Ballot,
    JudgingResult,
    ParadigmVerdict,
    build_diff_input,
    generate_diff,
)
from tests.conftest import (  # noqa: E402
    DETECTION_JSON,
    FLOW_STUB,
    FakeBedrockClient,
    PromptAwareFakeClient,
)

BALLOT = (
    "WINNER: AFF\nLEAN: clear\n"
    "RFD: The affirmative won on the dropped accident impact.\n"
    "SPEAKER POINTS: Aff 28 / Neg 27\nKEY VOTING ISSUES:\n1. A dropped warrant.\n"
)


def _ok_verdict(paradigm: str, winner: str = "AFF") -> ParadigmVerdict:
    v = ParadigmVerdict(paradigm=paradigm)
    for _ in range(3):
        b = Ballot(paradigm=paradigm)
        b.text = BALLOT.replace("WINNER: AFF", f"WINNER: {winner}")
        v.runs.append(b)
    return v


def _result(*verdicts: ParadigmVerdict) -> JudgingResult:
    r = JudgingResult()
    r.verdicts = list(verdicts)
    return r


# --- (b) one paradigm failed ------------------------------------------


def test_failed_paradigm_renders_the_marker_with_no_reason():
    failed = ParadigmVerdict(paradigm="circuit")  # no runs -> failed
    text = build_diff_input(
        "r1", "2026-08-17", "R", "A", "N",
        _result(_ok_verdict("traditional"), failed),
    )
    assert "Technical Circuit: [FAILED — no ballot]" in text
    # the surviving paradigm still carries its real decision + ballot
    assert "Traditional LD: clear AFF (3/3)" in text
    assert "dropped accident impact" in text


def test_diff_still_generates_with_one_failure():
    failed = ParadigmVerdict(paradigm="lay")
    client = FakeBedrockClient(responses=["=== JudgeAI — Cross-Paradigm Diff ==="])
    resp = generate_diff(
        client, "r1", "2026-08-17", "R", "A", "N",
        _result(failed, _ok_verdict("traditional"), _ok_verdict("circuit", "NEG")),
    )
    assert client.call_count == 1
    assert "Lay Parent: [FAILED — no ballot]" in client.calls[0]["user"]


# --- (c) >= 3 of 4 failed ---------------------------------------------


class NoParseableBallotClient(PromptAwareFakeClient):
    """Detection and flow succeed; every ballot comes back unparseable."""

    def invoke(self, system, user, **kwargs):
        with self._lock:
            if "Speech Boundaries" in system or "start_marker" in system:
                self._responses = [DETECTION_JSON]
            elif "Extract the flow" in system:
                self._responses = [FLOW_STUB]
            else:
                self._responses = ["(model returned no WINNER line)"]
            self._index = 0
            return FakeBedrockClient.invoke(self, system, user, **kwargs)


@pytest.fixture
def labeled_round(tmp_path, monkeypatch):
    from src import ingest, storage

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    monkeypatch.setattr(storage, "DEFAULT_BALLOTS_ROOT", tmp_path / "Ballots")
    folder = tmp_path / "New_Rounds" / "LD" / "mark_priya"
    folder.mkdir(parents=True)
    for name in ("1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR"):
        (folder / f"{name}.txt").write_text("word " * 60, encoding="utf-8")
    return folder, tmp_path / "Ballots"


def test_three_plus_failures_skip_the_diff_gracefully(labeled_round, monkeypatch):
    folder, ballots = labeled_round
    monkeypatch.setattr(
        "src.cli.build_client", lambda **_kw: NoParseableBallotClient()
    )
    result = CliRunner().invoke(
        cli_app(),
        ["new", str(folder), "--personas", "all", "--runs", "1"],
        input="\n\n\ny\n",
    )
    assert result.exit_code != 0
    assert "Too many persona failures (4/4)" in result.output
    assert "Diff skipped" in result.output
    # No diff should have been written.
    assert not list(ballots.rglob("diff.md"))


def cli_app():
    from src.cli import cli

    return cli
