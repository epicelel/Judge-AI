"""
Story 5.2 — `judge.py list` shows past rounds.

The storage layer already summarizes rounds (list_rounds, built with 5.1); this
covers the CLI command that renders them as a table.
"""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage import LocalDiskBallotStore  # noqa: E402

BALLOT = "WINNER: AFF\nRFD: x\nSPEAKER POINTS: Aff 28 / Neg 27\nKEY VOTING ISSUES:\n1. y\n"


def _cli():
    from src.cli import cli

    return cli


def _save_round(store, round_id, *, resolution, aff, date, personas=("lay",)):
    store.save_metadata(
        round_id,
        {
            "round_id": round_id,
            "date": date,
            "format": "LD",
            "resolution": resolution,
            "aff": aff,
        },
    )
    for p in personas:
        store.save_ballot(round_id, p, BALLOT)


def test_empty_shows_the_getting_started_message():
    # The autouse fixture points DEFAULT_BALLOTS_ROOT at an empty sandbox.
    result = CliRunner().invoke(_cli(), ["list"])
    assert result.exit_code == 0
    assert "No rounds judged yet" in result.output
    assert "judge.py new" in result.output


def test_list_shows_saved_rounds_as_a_table():
    store = LocalDiskBallotStore()
    _save_round(
        store,
        "847213.081126.civil-liberties.ishan",
        resolution="Civil liberties ought to be prioritized.",
        aff="Ishan",
        date="2026-08-11",
        personas=("lay", "circuit"),
    )
    result = CliRunner().invoke(_cli(), ["list"])
    assert result.exit_code == 0
    # 6-digit prefix with an ellipsis by default, not the full id.
    assert "847213…" in result.output
    assert "847213.081126.civil-liberties.ishan" not in result.output
    assert "Ishan" in result.output
    assert "Civil liberties" in result.output
    assert "lay" in result.output and "circuit" in result.output
    # header row is present
    assert "ROUND_ID" in result.output and "RESOLUTION" in result.output


def test_full_flag_shows_the_whole_round_id():
    store = LocalDiskBallotStore()
    _save_round(
        store,
        "847213.081126.civil-liberties.ishan",
        resolution="R",
        aff="Ishan",
        date="2026-08-11",
    )
    result = CliRunner().invoke(_cli(), ["list", "--full"])
    assert "847213.081126.civil-liberties.ishan" in result.output


def test_missing_fields_render_placeholders():
    store = LocalDiskBallotStore()
    _save_round(
        store,
        "111111.081126.unknown-resolution.unknown-aff",
        resolution=None,
        aff=None,
        date="2026-08-11",
    )
    result = CliRunner().invoke(_cli(), ["list"])
    assert "(no resolution)" in result.output
    assert "(no aff)" in result.output


def test_rounds_are_listed_newest_first():
    store = LocalDiskBallotStore()
    _save_round(store, "100000.081026.a.x", resolution="A", aff="X", date="2026-08-10")
    _save_round(store, "200000.081226.b.y", resolution="B", aff="Y", date="2026-08-12")
    result = CliRunner().invoke(_cli(), ["list"])
    assert result.output.index("200000…") < result.output.index("100000…")
