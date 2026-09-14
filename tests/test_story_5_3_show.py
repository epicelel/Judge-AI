"""
Story 5.3 — `judge.py show` re-prints a past round's diff or one ballot.

Storage already resolves prefixes and loads diffs/ballots; this covers the CLI.
"""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage import LocalDiskBallotStore  # noqa: E402

DIFF = "=== JudgeAI — Cross-Paradigm Diff ===\n—— PARADIGM DECISIONS ——\nLay Parent: clear AFF (3/3)\n"
CIRCUIT_BALLOT = "WINNER: NEG\nRFD: circuit reasoning here.\nKEY VOTING ISSUES:\n1. z\n"


def _cli():
    from src.cli import cli

    return cli


def _round(store, round_id, *, diff=DIFF, personas=("lay", "circuit")):
    store.save_metadata(round_id, {"round_id": round_id, "date": "2026-08-11"})
    for p in personas:
        body = CIRCUIT_BALLOT if p == "circuit" else "WINNER: AFF\nRFD: x\n"
        store.save_ballot(round_id, p, body)
    if diff is not None:
        store.save_diff(round_id, diff)


def test_show_prints_the_diff_by_prefix():
    store = LocalDiskBallotStore()
    _round(store, "847213.081126.civil-liberties.ishan")
    result = CliRunner().invoke(_cli(), ["show", "847213"])
    assert result.exit_code == 0
    assert "Cross-Paradigm Diff" in result.output


def test_show_accepts_the_full_round_id():
    store = LocalDiskBallotStore()
    _round(store, "847213.081126.civil-liberties.ishan")
    result = CliRunner().invoke(
        _cli(), ["show", "847213.081126.civil-liberties.ishan"]
    )
    assert result.exit_code == 0
    assert "PARADIGM DECISIONS" in result.output


def test_show_persona_prints_that_ballot():
    store = LocalDiskBallotStore()
    _round(store, "847213.081126.civil-liberties.ishan")
    result = CliRunner().invoke(_cli(), ["show", "847213", "--persona", "circuit"])
    assert result.exit_code == 0
    assert "circuit reasoning here" in result.output


def test_ambiguous_prefix_lists_matches():
    store = LocalDiskBallotStore()
    _round(store, "111111.081026.a.x")
    _round(store, "111111.081226.b.y")
    result = CliRunner().invoke(_cli(), ["show", "111111"])
    assert result.exit_code != 0
    assert "matches multiple rounds" in result.output
    assert "111111.081026.a.x" in result.output
    assert "111111.081226.b.y" in result.output


def test_unknown_round_is_a_friendly_error():
    result = CliRunner().invoke(_cli(), ["show", "999999"])
    assert result.exit_code != 0
    assert "Round '999999' not found" in result.output
    assert "judge.py list" in result.output


def test_unknown_persona_is_rejected():
    store = LocalDiskBallotStore()
    _round(store, "847213.081126.civil-liberties.ishan")
    result = CliRunner().invoke(_cli(), ["show", "847213", "--persona", "lyd"])
    assert result.exit_code != 0
    assert "Unknown persona 'lyd'" in result.output


def test_persona_not_judged_reports_what_is_available():
    store = LocalDiskBallotStore()
    _round(store, "847213.081126.civil-liberties.ishan", personas=("lay",))
    result = CliRunner().invoke(_cli(), ["show", "847213", "--persona", "circuit"])
    assert result.exit_code != 0
    assert "No Technical Circuit ballot" in result.output
    assert "lay" in result.output


def test_no_diff_suggests_persona():
    store = LocalDiskBallotStore()
    _round(store, "847213.081126.civil-liberties.ishan", diff=None, personas=("lay",))
    result = CliRunner().invoke(_cli(), ["show", "847213"])
    assert result.exit_code != 0
    assert "No diff saved" in result.output
    assert "--persona" in result.output
