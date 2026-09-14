"""
Phase 0 tests for the storage layer.

Covers Story 5.1 (save + Round_ID rules) and the machinery Stories 5.2/5.3/5.4
build on. Everything runs in tmp_path, so ~/Desktop is never touched.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage import (  # noqa: E402
    UNKNOWN_AFF,
    UNKNOWN_RESOLUTION,
    LocalDiskBallotStore,
    StorageError,
    generate_round_id,
    slugify,
)

NUCLEAR = "Resolved: The possession of nuclear weapons is immoral."


# --- Round_ID construction (Story 5.1) --------------------------------


def test_slugify_drops_stopwords_and_keeps_keywords():
    assert slugify(NUCLEAR) == "possession-nuclear-weapons"


def test_slugify_is_filesystem_safe():
    assert slugify("Civil liberties vs. national security!") == "civil-liberties-vs"


def test_slugify_returns_empty_for_missing_text():
    assert slugify(None) == "" and slugify("   ") == ""


def test_round_id_has_all_four_segments():
    round_id = generate_round_id(
        {"resolution": NUCLEAR, "aff": "Eliana", "date": "2026-08-11"}
    )
    numeric, date_part, resolution_part, aff_part = round_id.split(".")
    assert numeric.isdigit() and len(numeric) == 6
    assert date_part == "081126"
    assert resolution_part == "possession-nuclear-weapons"
    assert aff_part == "eliana"


def test_round_id_falls_back_to_unknown_slugs():
    round_id = generate_round_id({"date": "2026-08-11"})
    assert round_id.endswith(f".{UNKNOWN_RESOLUTION}.{UNKNOWN_AFF}")


def test_round_id_still_unique_without_metadata():
    meta = {"date": "2026-08-11"}
    ids = {generate_round_id(meta) for _ in range(50)}
    assert len(ids) > 1  # the 6-digit prefix carries uniqueness


def test_round_id_avoids_colliding_with_existing_ids(monkeypatch):
    """Story 5.1: regenerate until the 6-digit prefix is unused."""
    sequence = iter([424242, 424242, 999111])
    monkeypatch.setattr("src.storage.random.randint", lambda *_: next(sequence))
    existing = ["424242.081126.possession-nuclear-weapons.eliana"]
    round_id = generate_round_id({"date": "2026-08-11"}, existing_ids=existing)
    assert round_id.startswith("999111.")


def test_round_id_uses_today_when_date_missing():
    from datetime import datetime

    round_id = generate_round_id({"resolution": NUCLEAR})
    assert round_id.split(".")[1] == datetime.now().strftime("%m%d%y")


# --- save / load round-trip (Story 5.1) -------------------------------


def test_saved_round_contains_all_expected_files(store):
    round_id = "847213.081126.possession-nuclear-weapons.eliana"
    store.save_metadata(round_id, {"resolution": NUCLEAR, "aff": "Eliana"})
    store.save_transcript(round_id, "=== 1AC ===\n...")
    store.save_diff(round_id, "—— PARADIGM DECISIONS ——")
    store.save_ballot(round_id, "lay", "WINNER: AFF")

    names = {p.name for p in store.round_path(round_id).iterdir()}
    assert names == {
        "metadata.json",
        "structured_transcript.md",
        "diff.md",
        "judge_lay.md",
    }


def test_ballot_round_trips(store):
    store.save_ballot("r1", "circuit", "WINNER: NEG\nRFD: ...")
    assert store.load_ballot("r1", "circuit") == "WINNER: NEG\nRFD: ..."


def test_metadata_round_trips_as_json(store):
    meta = {"resolution": NUCLEAR, "aff": "Eliana", "token_usage": {"lay": {"cost_usd": 0.02}}}
    store.save_metadata("r1", meta)
    assert store.load_metadata("r1") == meta
    assert json.loads((store.round_path("r1") / "metadata.json").read_text())


def test_diff_round_trips(store):
    store.save_diff("r1", "diff body")
    assert store.load_diff("r1") == "diff body"


def test_loading_a_missing_ballot_raises_storage_error(store):
    with pytest.raises(StorageError):
        store.load_ballot("nope", "lay")


def test_unwritable_location_raises_storage_error(tmp_path):
    """Story 5.1: the CLI needs a catchable error so it can fall back to stdout."""
    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file, not a directory")
    store = LocalDiskBallotStore(base_path=blocker)
    with pytest.raises(StorageError):
        store.save_ballot("r1", "lay", "content")


def test_personas_for_lists_only_saved_ballots(store):
    store.save_ballot("r1", "lay", "x")
    store.save_ballot("r1", "circuit", "x")
    store.save_diff("r1", "not a ballot")
    assert store.personas_for("r1") == ["circuit", "lay"]


# --- listing (Story 5.2) ----------------------------------------------


def test_list_rounds_is_empty_before_anything_is_judged(store):
    assert store.list_rounds() == []


def test_list_rounds_summarizes_each_round(store):
    round_id = "847213.081126.possession-nuclear-weapons.eliana"
    store.save_metadata(
        round_id,
        {"date": "2026-08-11", "format": "LD", "resolution": NUCLEAR, "aff": "Eliana"},
    )
    store.save_ballot(round_id, "lay", "x")
    store.save_ballot(round_id, "flow", "x")

    (summary,) = store.list_rounds()
    assert summary["short_id"] == "847213"
    assert summary["format"] == "LD"
    assert summary["aff"] == "Eliana"
    assert summary["paradigms"] == ["flow", "lay"]


def test_list_rounds_tolerates_missing_metadata(store):
    """Story 5.2: rounds with absent metadata still appear, with blank fields."""
    store.save_ballot("999999.081126.unknown-resolution.unknown-aff", "lay", "x")
    (summary,) = store.list_rounds()
    assert summary["resolution"] is None and summary["paradigms"] == ["lay"]


def test_list_rounds_sums_cost_across_paradigms(store):
    store.save_metadata(
        "r1",
        {"token_usage": {"lay": {"cost_usd": 0.02}, "circuit": {"cost_usd": 0.03}}},
    )
    assert store.list_rounds()[0]["cost_usd"] == pytest.approx(0.05)


# --- id resolution (Story 5.3) ----------------------------------------


def test_six_digit_prefix_resolves_to_full_round_id(store):
    round_id = "847213.081126.possession-nuclear-weapons.eliana"
    store.save_diff(round_id, "d")
    assert store.resolve_round_id("847213") == [round_id]


def test_full_round_id_resolves_to_itself(store):
    round_id = "847213.081126.possession-nuclear-weapons.eliana"
    store.save_diff(round_id, "d")
    assert store.resolve_round_id(round_id) == [round_id]


def test_ambiguous_prefix_returns_every_match(store):
    """Story 5.3: the caller must be able to ask the user to disambiguate."""
    store.save_diff("847213.081126.aaa.eliana", "d")
    store.save_diff("847999.081126.bbb.marcus", "d")
    assert len(store.resolve_round_id("847")) == 2


def test_unknown_id_resolves_to_nothing(store):
    assert store.resolve_round_id("000000") == []


# --- deletion (Story 5.4) ---------------------------------------------


def test_delete_round_removes_the_whole_folder(store):
    store.save_ballot("r1", "lay", "x")
    store.save_diff("r1", "d")
    store.delete_round("r1")
    assert not store.round_path("r1").exists()


def test_delete_round_leaves_other_rounds_intact(store):
    store.save_diff("r1", "d")
    store.save_diff("r2", "d")
    store.delete_round("r1")
    assert store.round_path("r2").exists()


def test_deleting_a_missing_round_raises_storage_error(store):
    with pytest.raises(StorageError):
        store.delete_round("nope")
