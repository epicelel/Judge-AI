"""
Story 2.3 — Skip detection when files are already labeled.

Recognizable filenames are labeled without a model call, and reordered into the
canonical debate sequence. Ambiguous names fall through to model detection
(Story 2.1). Everything here is pure string work: no model, no cost.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.structure import (  # noqa: E402
    AFF,
    BOTH,
    LD_SEQUENCE,
    NEG,
    SOURCE_FILENAME,
    SOURCE_UNLABELED,
    expected_labels,
    label_files,
    label_from_filename,
    order_speech_files,
    slot_for,
)


def paths(*names) -> list:
    return [Path(name) for name in names]


# --- The canonical sequence (Story 2.3 ordering authority) --------------


def test_ld_sequence_is_the_seven_documented_speeches():
    assert expected_labels("LD") == ["1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR"]


@pytest.mark.parametrize(
    "label,speaker",
    [("1AC", AFF), ("CX1", BOTH), ("1NC", NEG), ("CX2", BOTH),
     ("1AR", AFF), ("2NR", NEG), ("2AR", AFF)],
)
def test_each_speech_has_the_documented_speaker(label, speaker):
    assert slot_for(label).speaker == speaker


def test_positions_are_sequential_and_unique():
    positions = [slot.position for slot in LD_SEQUENCE]
    assert positions == list(range(1, 8))


def test_cross_examination_describes_who_questions_whom():
    assert slot_for("CX1").description == "Neg questions Aff"
    assert slot_for("CX2").description == "Aff questions Neg"


def test_unsupported_format_has_no_sequence():
    """PF/Worlds/etc. arrive in v0.5; until then there is nothing to match."""
    assert expected_labels("PF") == []


# --- Recognized filename patterns --------------------------------------


@pytest.mark.parametrize("label", ["1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR"])
def test_every_canonical_label_is_recognized_bare(label):
    assert label_from_filename(Path(f"{label}.txt")) == label


@pytest.mark.parametrize("name", ["1ac.txt", "1Ac.txt", "1AC.TXT", "cx1.txt", "Cx1.txt"])
def test_recognition_is_case_insensitive(name):
    assert label_from_filename(Path(name)) is not None


@pytest.mark.parametrize("name", ["01_1AC.txt", "1_1AC.txt", "001_1AC.txt", "01-1AC.txt"])
def test_numeric_index_prefixes_are_stripped(name):
    assert label_from_filename(Path(name)) == "1AC"


@pytest.mark.parametrize("name", ["1-AC.txt", "1_AC.txt", "1 AC.txt"])
def test_separators_between_number_and_label_are_tolerated(name):
    assert label_from_filename(Path(name)) == "1AC"


@pytest.mark.parametrize(
    "name,label",
    [("CX1.txt", "CX1"), ("cross_1.txt", "CX1"), ("crossex1.txt", "CX1"),
     ("cross-examination-1.txt", "CX1"), ("CX_2.txt", "CX2"), ("cross_2.txt", "CX2"),
     ("1cx.txt", "CX1"), ("2cross.txt", "CX2")],
)
def test_cross_examination_spellings(name, label):
    assert label_from_filename(Path(name)) == label


def test_bare_cx_means_the_first_cross_examination():
    assert label_from_filename(Path("CX.txt")) == "CX1"


@pytest.mark.parametrize(
    "name,label",
    [("AC.txt", "1AC"), ("NC.txt", "1NC"), ("AR.txt", "1AR"), ("NR.txt", "2NR")],
)
def test_bare_aliases_resolve_since_ld_has_one_of_each(name, label):
    assert label_from_filename(Path(name)) == label


@pytest.mark.parametrize(
    "name,label",
    [("aff_constructive.txt", "1AC"), ("affirmative_constructive.txt", "1AC"),
     ("neg_constructive.txt", "1NC"), ("negative_constructive.txt", "1NC")],
)
def test_spelled_out_constructives_are_recognized(name, label):
    """README documents aff_constructive.txt as a recognized 1AC."""
    assert label_from_filename(Path(name)) == label


@pytest.mark.parametrize("name", ["1AC_final.txt", "1AC-copy.txt", "1AC_v2.txt"])
def test_extra_suffixes_do_not_defeat_recognition(name):
    assert label_from_filename(Path(name)) == "1AC"


# --- Names that must NOT be guessed -----------------------------------


@pytest.mark.parametrize("name", ["speech_01.txt", "speech_02.txt", "part1.txt",
                                  "recording.txt", "round.txt", "otter_export.txt"])
def test_ambiguous_names_are_left_unlabeled(name):
    assert label_from_filename(Path(name)) is None


def test_non_canonical_speech_numbers_are_rejected():
    """LD has no 3AC or 2AC; guessing would mis-order the round."""
    assert label_from_filename(Path("3AC.txt")) is None
    assert label_from_filename(Path("2AC.txt")) is None


def test_out_of_range_cross_examination_is_rejected():
    assert label_from_filename(Path("CX3.txt")) is None


def test_word_form_rebuttals_are_deliberately_not_guessed():
    """"aff_rebuttal" could be 1AR or 2AR — falling through beats guessing."""
    assert label_from_filename(Path("aff_rebuttal.txt")) is None


def test_a_name_matching_two_labels_is_not_guessed():
    assert label_from_filename(Path("1AC_and_1NC.txt")) is None


# --- Ordering: the bug this story closes ------------------------------


def test_bare_labels_are_reordered_into_debate_order():
    scrambled = paths("1AC.txt", "1AR.txt", "1NC.txt", "2AR.txt", "2NR.txt",
                      "CX1.txt", "CX2.txt")
    assert [p.stem for p in order_speech_files(scrambled)] == [
        "1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR"
    ]


def test_already_correct_order_is_preserved():
    ordered = paths("1AC.txt", "CX1.txt", "1NC.txt", "CX2.txt", "1AR.txt",
                    "2NR.txt", "2AR.txt")
    assert order_speech_files(ordered) == ordered


def test_reversed_input_is_corrected():
    reversed_files = paths("2AR.txt", "2NR.txt", "1AR.txt", "CX2.txt", "1NC.txt",
                           "CX1.txt", "1AC.txt")
    assert [p.stem for p in order_speech_files(reversed_files)][0] == "1AC"


def test_numeric_prefixed_files_end_up_in_the_same_order():
    """Prefixed names already sorted correctly; labeling must not disturb them."""
    prefixed = paths("01_1AC.txt", "02_CX1.txt", "03_1NC.txt")
    assert order_speech_files(prefixed) == prefixed


def test_unlabeled_files_keep_their_relative_order_after_labeled_ones():
    mixed = paths("speech_02.txt", "1AC.txt", "speech_01.txt")
    assert [p.stem for p in order_speech_files(mixed)] == [
        "1AC", "speech_02", "speech_01"
    ]


# --- Skipping the model call ------------------------------------------


def test_fully_labeled_folder_skips_model_detection():
    result = label_files(paths("1AC.txt", "CX1.txt", "1NC.txt", "CX2.txt",
                               "1AR.txt", "2NR.txt", "2AR.txt"))
    assert result.all_labeled is True
    assert result.needs_model is False
    assert result.labeled_count == 7


def test_labels_record_that_they_came_from_the_filename():
    result = label_files(paths("1AC.txt"))
    assert result.speeches[0].source == SOURCE_FILENAME


def test_labeled_speeches_carry_speaker_and_position():
    result = label_files(paths("CX1.txt", "1AC.txt"))
    first = result.speeches[0]
    assert (first.label, first.speaker, first.position) == ("1AC", AFF, 1)


# --- Ambiguous folders fall through to the model ---------------------


def test_all_ambiguous_names_require_model_detection():
    result = label_files(paths("speech_01.txt", "speech_02.txt", "speech_03.txt"))
    assert result.all_labeled is False
    assert result.needs_model is True
    assert result.labeled_count == 0
    assert all(s.source == SOURCE_UNLABELED for s in result.speeches)


def test_partially_labeled_folder_keeps_hints_and_still_needs_the_model():
    """Story 2.3: filename hints where clear, model labeling where not."""
    result = label_files(paths("1AC.txt", "speech_02.txt", "1NC.txt"))
    assert result.needs_model is True
    assert result.labeled_count == 2
    labeled = {s.label for s in result.speeches if s.is_labeled}
    assert labeled == {"1AC", "1NC"}


def test_missing_labels_are_reported():
    result = label_files(paths("1AC.txt", "1NC.txt"))
    assert result.missing_labels == ["CX1", "CX2", "1AR", "2NR", "2AR"]


def test_duplicate_labels_are_flagged_and_ordering_is_left_alone():
    """Two files claiming 1AC: don't pick a winner, don't half-reorder."""
    files = paths("1AC.txt", "01_1AC.txt", "1NC.txt")
    result = label_files(files)
    assert result.duplicates == ["1AC"]
    assert result.needs_model is True
    assert [s.path for s in result.speeches] == files


def test_empty_folder_is_not_considered_labeled():
    result = label_files([])
    assert result.all_labeled is False


# --- Integration with loading ----------------------------------------


def test_loading_a_labeled_folder_yields_canonical_order(tmp_path, monkeypatch):
    from src import ingest
    from src.ingest import load_round_input

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    folder = tmp_path / "New_Rounds" / "LD" / "mark_priya"
    folder.mkdir(parents=True)
    body = "transcript filler text " * 30
    for name in ("2AR", "1AC", "CX2", "1NC", "CX1", "2NR", "1AR"):
        (folder / f"{name}.txt").write_text(body, encoding="utf-8")

    (round_input,) = load_round_input(str(folder), confirm=lambda _m: True)

    assert [f.stem for f in round_input.files] == [
        "1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR"
    ]


def test_loading_an_unlabeled_folder_keeps_natural_order(tmp_path, monkeypatch):
    """speech_2 before speech_10 — tier 2 of the ordering rule still applies."""
    from src import ingest
    from src.ingest import load_round_input

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    folder = tmp_path / "New_Rounds" / "LD" / "unlabeled"
    folder.mkdir(parents=True)
    body = "transcript filler text " * 30
    for index in (1, 2, 10):
        (folder / f"speech_{index}.txt").write_text(body, encoding="utf-8")

    (round_input,) = load_round_input(str(folder), confirm=lambda _m: True)

    assert [f.stem for f in round_input.files] == ["speech_1", "speech_2", "speech_10"]
