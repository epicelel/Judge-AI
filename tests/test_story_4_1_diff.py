"""
Story 4.1 — the primary output is a compact cross-paradigm diff.

Offline unit tests over the diff assembly (the model call is stubbed), plus a CLI
integration test that a multi-persona run emits the diff and saves diff.md.
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
    diff_decision_line,
    generate_diff,
)
from tests.conftest import FakeBedrockClient  # noqa: E402

BALLOT = """WINNER: AFF
LEAN: clear
RFD: The affirmative won on the dropped Randall '22 accident impact.
SPEAKER POINTS: Aff 28 / Neg 27
KEY VOTING ISSUES:
1. The Randall '22 warrant went unanswered.
"""


def _ballot(winner: str) -> Ballot:
    b = Ballot(paradigm="x")
    b.text = BALLOT.replace("WINNER: AFF", f"WINNER: {winner}")
    return b


def _verdict(paradigm: str, winner: str, n: int = 3) -> ParadigmVerdict:
    v = ParadigmVerdict(paradigm=paradigm)
    v.runs = [_ballot(winner) for _ in range(n)]
    return v


def _result(*verdicts: ParadigmVerdict) -> JudgingResult:
    r = JudgingResult()
    r.verdicts = list(verdicts)
    return r


# --- decision line ----------------------------------------------------


def test_decision_line_is_label_first_with_share():
    v = _verdict("traditional", "AFF", n=3)
    assert diff_decision_line(v) == "clear AFF (3/3)"


def test_decision_line_shows_a_slight_lean_split():
    v = ParadigmVerdict(paradigm="circuit")
    v.runs = [_ballot("AFF"), _ballot("AFF"), _ballot("NEG")]
    assert diff_decision_line(v) == "slight lean AFF (2/3)"


# --- build_diff_input -------------------------------------------------


def test_input_carries_the_round_header():
    text = build_diff_input(
        "123456.081726.nukes.eliana",
        "2026-08-17",
        "The possession of nuclear weapons is immoral.",
        "Eliana",
        "Marcus",
        _result(_verdict("traditional", "AFF")),
    )
    assert "123456.081726.nukes.eliana" in text
    assert '"The possession of nuclear weapons is immoral."' in text
    assert "Aff: Eliana | Neg: Marcus" in text


def test_input_gives_each_paradigm_a_verbatim_decision_and_its_ballot():
    text = build_diff_input(
        "r1", "2026-08-17", "R", "A", "N",
        _result(_verdict("traditional", "AFF"), _verdict("circuit", "NEG")),
    )
    assert "DECISION (use verbatim): Traditional LD: clear AFF (3/3)" in text
    assert "DECISION (use verbatim): Technical Circuit: clear NEG (3/3)" in text
    # The ballot body travels with it so the diff can name specific arguments.
    assert "Randall '22" in text


def test_input_flags_a_blowout_when_paradigms_agree():
    text = build_diff_input(
        "r1", "2026-08-17", "R", "A", "N",
        _result(_verdict("traditional", "AFF"), _verdict("circuit", "AFF")),
    )
    assert "SAME winner" in text


def test_input_omits_the_blowout_note_when_paradigms_split():
    text = build_diff_input(
        "r1", "2026-08-17", "R", "A", "N",
        _result(_verdict("traditional", "AFF"), _verdict("circuit", "NEG")),
    )
    assert "SAME winner" not in text


def test_input_marks_a_failed_paradigm():  # behavior changed by Story 4.3
    failed = ParadigmVerdict(paradigm="lay")  # no runs -> failed
    text = build_diff_input(
        "r1", "2026-08-17", "R", "A", "N",
        _result(failed, _verdict("traditional", "AFF")),
    )
    assert "Traditional LD: clear AFF (3/3)" in text
    assert "Lay Parent: [FAILED — no ballot]" in text


# --- generate_diff ----------------------------------------------------


def test_generate_diff_calls_the_diff_prompt():
    client = FakeBedrockClient(responses=["=== JudgeAI — Cross-Paradigm Diff ==="])
    resp = generate_diff(
        client, "r1", "2026-08-17", "R", "A", "N",
        _result(_verdict("traditional", "AFF"), _verdict("circuit", "AFF")),
    )
    assert client.call_count == 1
    assert "CROSS-PARADIGM DIFF" in client.calls[0]["system"]
    assert "DECISION (use verbatim)" in client.calls[0]["user"]
    assert resp.text.startswith("=== JudgeAI")


# --- CLI integration --------------------------------------------------


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


def _cli():
    from src.cli import cli

    return cli


def test_multi_persona_run_emits_the_diff_and_saves_it(labeled_round):
    folder, ballots = labeled_round
    result = CliRunner().invoke(
        _cli(),
        ["new", str(folder), "--personas", "traditional,circuit", "--runs", "1"],
        input="\n\n\ny\n",
    )
    assert result.exit_code == 0, result.output
    assert "=== JudgeAI — Cross-Paradigm Diff ===" in result.output
    diffs = list(ballots.rglob("diff.md"))
    assert len(diffs) == 1
    assert "PARADIGM DECISIONS" in diffs[0].read_text()
