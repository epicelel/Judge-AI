"""
Story 5.4 — `judge.py rm` deletes a round's ballots after confirmation.

delete_round (storage) removes only the Ballots folder; archived inputs under
Past_Rounds/ are a separate archive and must survive.
"""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import archive  # noqa: E402
from src.storage import LocalDiskBallotStore  # noqa: E402

RID = "847213.081126.civil-liberties.ishan"


def _cli():
    from src.cli import cli

    return cli


def _round(store, round_id=RID):
    store.save_metadata(round_id, {"round_id": round_id, "date": "2026-08-11"})
    store.save_ballot(round_id, "lay", "WINNER: AFF\nRFD: x\n")


def test_confirming_deletes_the_round():
    store = LocalDiskBallotStore()
    _round(store)
    assert store.round_path(RID).exists()
    result = CliRunner().invoke(_cli(), ["rm", "847213"], input="y\n")
    assert result.exit_code == 0
    assert "and all its ballots?" in result.output  # the exact prompt shape
    assert "[y/N]" in result.output
    assert "Deleted round" in result.output
    assert not store.round_path(RID).exists()


def test_declining_keeps_the_round():
    store = LocalDiskBallotStore()
    _round(store)
    result = CliRunner().invoke(_cli(), ["rm", "847213"], input="n\n")
    assert result.exit_code == 0
    assert "Nothing deleted" in result.output
    assert store.round_path(RID).exists()


def test_pressing_enter_keeps_the_round():
    store = LocalDiskBallotStore()
    _round(store)
    result = CliRunner().invoke(_cli(), ["rm", "847213"], input="\n")
    assert "Nothing deleted" in result.output
    assert store.round_path(RID).exists()


def test_yes_flag_skips_the_prompt():
    store = LocalDiskBallotStore()
    _round(store)
    result = CliRunner().invoke(_cli(), ["rm", "847213", "--yes"])
    assert result.exit_code == 0
    assert "and all its ballots?" not in result.output
    assert not store.round_path(RID).exists()


def test_rm_leaves_the_archived_input_untouched(monkeypatch):
    store = LocalDiskBallotStore()
    _round(store)
    # An archived input for the same round lives under a separate root.
    archived = archive.ARCHIVE_ROOT / "LD" / f"{RID}.txt"
    archived.parent.mkdir(parents=True, exist_ok=True)
    archived.write_text("original transcript", encoding="utf-8")

    CliRunner().invoke(_cli(), ["rm", "847213", "--yes"])

    assert not store.round_path(RID).exists()
    assert archived.exists()  # the archive is the user's to manage by hand


def test_unknown_round_is_a_friendly_error():
    result = CliRunner().invoke(_cli(), ["rm", "999999"], input="y\n")
    assert result.exit_code != 0
    assert "Round '999999' not found" in result.output


def test_ambiguous_prefix_lists_matches_and_deletes_nothing():
    store = LocalDiskBallotStore()
    _round(store, "111111.081026.a.x")
    _round(store, "111111.081226.b.y")
    result = CliRunner().invoke(_cli(), ["rm", "111111"], input="y\n")
    assert result.exit_code != 0
    assert "matches multiple rounds" in result.output
    assert store.round_path("111111.081026.a.x").exists()
    assert store.round_path("111111.081226.b.y").exists()
