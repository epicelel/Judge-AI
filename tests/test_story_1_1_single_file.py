"""
Story 1.1 — Judge a round from a single text file.

Each test name restates one Given/When/Then from the story's acceptance
criteria. All offline: the inbox is redirected into tmp_path, so no test reads
or writes the real ~/Desktop/JudgeAI.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import ingest  # noqa: E402
from src.ingest import (  # noqa: E402
    MIN_TRANSCRIPT_CHARS,
    IngestError,
    inbox_for,
    is_debate_format,
    list_inbox_items,
    load_round_input,
)

# A body long enough to clear the 200-char floor.
TRANSCRIPT_BODY = (
    "Resolved: The possession of nuclear weapons is immoral. "
    "My value is morality and my criterion is preventing death. "
    "Contention one: nuclear weapons create existential risk through "
    "accident, miscalculation, and environmental contamination. "
    "I strongly affirm the resolution and stand ready for cross-examination."
)


@pytest.fixture
def inbox(tmp_path, monkeypatch) -> Path:
    """Redirect the inbox into tmp_path and return the LD folder."""
    root = tmp_path / "JudgeAI" / "New_Rounds"
    monkeypatch.setattr(ingest, "INBOX_ROOT", root)
    ld = root / "LD"
    ld.mkdir(parents=True)
    return ld


def accept_count(_message: str) -> bool:
    """Story 1.2 count validation is exercised in its own test module."""
    return True


def write_round(folder: Path, name: str = "round.txt", body: str = TRANSCRIPT_BODY) -> Path:
    path = folder / name
    path.write_text(body, encoding="utf-8")
    return path


# --- Given a full round in the inbox, when I run `new LD` ----------------


def test_debate_type_auto_picks_the_only_round_in_the_inbox(inbox):
    write_round(inbox)
    (round_input,) = load_round_input("LD")
    assert round_input.name == "round.txt"
    assert round_input.is_folder is False
    assert round_input.files == [inbox / "round.txt"]


def test_explicit_path_is_accepted(inbox):
    path = write_round(inbox)
    (round_input,) = load_round_input(str(path))
    assert round_input.files == [path]


def test_debate_type_is_case_insensitive(inbox):
    write_round(inbox)
    assert load_round_input("ld")[0].debate_format == "LD"


def test_every_v01_debate_type_is_recognized_as_a_type_not_a_path():
    for value in ("LD", "PF", "Worlds", "Congress", "Parli"):
        assert is_debate_format(value)
    assert not is_debate_format("round.txt")


def test_accepted_round_carries_its_text_through(inbox):
    write_round(inbox)
    (round_input,) = load_round_input("LD")
    assert "possession of nuclear weapons" in round_input.read_text()


def test_home_relative_paths_are_expanded(inbox, monkeypatch):
    """`~` in a path must resolve, since that's how the inbox is documented."""
    path = write_round(inbox)
    monkeypatch.setenv("HOME", str(path.parent))
    (round_input,) = load_round_input("~/round.txt")
    assert round_input.files[0].name == "round.txt"


# --- Given an empty inbox ------------------------------------------------


def test_empty_inbox_names_the_folder_and_says_what_to_do(inbox):
    with pytest.raises(IngestError) as caught:
        load_round_input("LD")
    message = str(caught.value)
    assert "No rounds found in" in message
    assert str(inbox) in message
    assert "Drop transcript files there and try again." in message


def test_missing_inbox_folder_is_reported_as_empty_not_crashed(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "does_not_exist")
    with pytest.raises(IngestError) as caught:
        load_round_input("LD")
    assert "No rounds found in" in str(caught.value)


def test_inbox_holding_only_hidden_files_counts_as_empty(inbox):
    (inbox / ".DS_Store").write_bytes(b"\x00\x01")
    with pytest.raises(IngestError):
        load_round_input("LD")


# --- Given multiple items in the inbox -----------------------------------


def test_multiple_items_are_listed_for_the_user_to_pick(inbox):
    write_round(inbox, "round_a.txt")
    write_round(inbox, "round_b.txt")
    offered = {}

    def chooser(items):
        offered["names"] = [p.name for p in items]
        return 1  # pick the second

    (round_input,) = load_round_input("LD", chooser=chooser)
    assert offered["names"] == ["round_a.txt", "round_b.txt"]
    assert round_input.name == "round_b.txt"


def test_all_flag_judges_every_inbox_round_in_sequence(inbox):
    write_round(inbox, "round_a.txt")
    write_round(inbox, "round_b.txt")
    rounds = load_round_input("LD", select_all=True)
    assert [r.name for r in rounds] == ["round_a.txt", "round_b.txt"]


def test_choosing_judge_all_from_the_picker_returns_every_round(inbox):
    write_round(inbox, "round_a.txt")
    write_round(inbox, "round_b.txt")
    rounds = load_round_input("LD", chooser=lambda items: -1)
    assert len(rounds) == 2


def test_single_item_inbox_never_prompts(inbox):
    write_round(inbox)

    def chooser(_items):
        raise AssertionError("must not prompt when there is only one round")

    assert len(load_round_input("LD", chooser=chooser)) == 1


def test_inbox_listing_shows_folders_and_files(inbox):
    write_round(inbox, "loose_round.txt")
    speech_folder = inbox / "mark_priya"
    speech_folder.mkdir()
    write_round(speech_folder, "1AC.txt")

    names = [p.name for p in list_inbox_items("LD")]
    assert names == ["mark_priya", "loose_round.txt"]  # folders first


def test_inbox_listing_ignores_stray_non_transcript_files(inbox):
    write_round(inbox)
    (inbox / "notes.docx").write_text("x")
    (inbox / "audio.m4a").write_bytes(b"\x00")
    assert [p.name for p in list_inbox_items("LD")] == ["round.txt"]


# --- Given the path doesn't exist ---------------------------------------


def test_missing_path_error_names_the_path_and_the_valid_alternatives():
    with pytest.raises(IngestError) as caught:
        load_round_input("/tmp/definitely/not/here.txt")
    message = str(caught.value)
    assert "File not found: /tmp/definitely/not/here.txt" in message
    assert "Provide a valid .txt file, a folder of speech files, or a debate type" in message
    assert "LD/PF/Worlds/Congress/Parli" in message


def test_unknown_debate_type_is_treated_as_a_path():
    """`new XYZ` isn't a format, so it must fail as a missing path."""
    with pytest.raises(IngestError) as caught:
        load_round_input("XYZ")
    assert "File not found" in str(caught.value)


# --- Given the file isn't .txt ------------------------------------------


def test_docx_is_rejected_by_extension(tmp_path):
    path = tmp_path / "round.docx"
    path.write_text(TRANSCRIPT_BODY)
    with pytest.raises(IngestError) as caught:
        load_round_input(str(path))
    assert str(caught.value) == (
        "Unsupported file type: .docx. "
        "v0.1 accepts .txt and .rtf files, or folders of them."
    )


def test_pdf_is_rejected_by_extension(tmp_path):
    path = tmp_path / "round.pdf"
    path.write_text(TRANSCRIPT_BODY)
    with pytest.raises(IngestError) as caught:
        load_round_input(str(path))
    assert "Unsupported file type: .pdf" in str(caught.value)


def test_extension_check_is_case_insensitive(tmp_path):
    path = tmp_path / "ROUND.TXT"
    path.write_text(TRANSCRIPT_BODY)
    assert load_round_input(str(path))[0].files == [path]


# --- Given the file is empty or under 200 characters --------------------


def test_empty_file_is_rejected_as_too_short(tmp_path):
    path = tmp_path / "round.txt"
    path.write_text("")
    with pytest.raises(IngestError) as caught:
        load_round_input(str(path))
    assert str(caught.value) == (
        "Transcript too short (<200 chars). Not a real round."
    )


def test_file_just_under_the_floor_is_rejected(tmp_path):
    path = tmp_path / "round.txt"
    path.write_text("a" * (MIN_TRANSCRIPT_CHARS - 1))
    with pytest.raises(IngestError):
        load_round_input(str(path))


def test_file_at_the_floor_is_accepted(tmp_path):
    path = tmp_path / "round.txt"
    path.write_text("a" * MIN_TRANSCRIPT_CHARS)
    assert load_round_input(str(path))[0].files == [path]


def test_whitespace_only_file_is_rejected(tmp_path):
    """300 spaces is not a round, so length is measured on stripped text."""
    path = tmp_path / "round.txt"
    path.write_text(" \n\t" * 100)
    with pytest.raises(IngestError) as caught:
        load_round_input(str(path))
    assert "too short" in str(caught.value)


# --- Folder inputs: enough for 1.1; validation arrives in Story 1.2 -----


def test_folder_of_speech_files_is_loaded_as_a_folder_round(inbox):
    folder = inbox / "mark_priya"
    folder.mkdir()
    for name in ("1AC.txt", "CX1.txt", "1NC.txt"):
        write_round(folder, name)
    (round_input,) = load_round_input(str(folder), confirm=accept_count)
    assert round_input.is_folder is True
    assert len(round_input.files) == 3


def test_numeric_prefixes_produce_correct_debate_order(inbox):
    """The naming scheme Story 2.3 recommends sorts correctly on its own."""
    folder = inbox / "prefixed"
    folder.mkdir()
    for name in ("02_CX1.txt", "01_1AC.txt", "03_1NC.txt"):
        write_round(folder, name)
    (round_input,) = load_round_input(str(folder), confirm=accept_count)
    assert [f.name for f in round_input.files] == [
        "01_1AC.txt",
        "02_CX1.txt",
        "03_1NC.txt",
    ]


def test_bare_speech_labels_sort_into_canonical_debate_order(inbox):
    """
    Closed by Story 2.3 (was: pinned the alphanumeric scramble).

    Alphanumeric ordering gave 1AC, 1AR, 1NC, 2AR, 2NR, CX1, CX2 — the 1AR
    landing before the 1NC it answers. Filename labeling now reorders to the
    sequence the round was actually debated in.
    """
    folder = inbox / "bare_labels"
    folder.mkdir()
    for name in ("1AC.txt", "CX1.txt", "1NC.txt", "CX2.txt", "1AR.txt", "2NR.txt", "2AR.txt"):
        write_round(folder, name)
    (round_input,) = load_round_input(str(folder), confirm=accept_count)
    assert [f.stem for f in round_input.files] == [
        "1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR",
    ]


def test_numbered_speech_files_sort_naturally_not_lexicographically(inbox):
    """speech_2 must precede speech_10, or the round is judged out of order."""
    folder = inbox / "unlabeled"
    folder.mkdir()
    for index in (1, 2, 10):
        write_round(folder, f"speech_{index}.txt")
    (round_input,) = load_round_input(str(folder), confirm=accept_count)
    assert [f.name for f in round_input.files] == [
        "speech_1.txt",
        "speech_2.txt",
        "speech_10.txt",
    ]


def test_folder_with_no_transcripts_is_rejected(inbox):
    folder = inbox / "empty"
    folder.mkdir()
    (folder / "notes.docx").write_text("x")
    with pytest.raises(IngestError) as caught:
        load_round_input(str(folder), confirm=accept_count)
    assert "No speech files found" in str(caught.value)


def test_short_speech_file_inside_a_folder_is_rejected(inbox):
    folder = inbox / "mark_priya"
    folder.mkdir()
    write_round(folder, "1AC.txt")
    (folder / "1NC.txt").write_text("too short")
    with pytest.raises(IngestError) as caught:
        load_round_input(str(folder), confirm=accept_count)
    assert "too short" in str(caught.value)


def test_round_yaml_sidecar_is_noticed(inbox):
    """Story 1.3 reads it; 1.1 only needs to find it."""
    folder = inbox / "mark_priya"
    folder.mkdir()
    write_round(folder, "1AC.txt")
    (folder / "round.yaml").write_text("resolution: test\n")
    (round_input,) = load_round_input(str(folder), confirm=accept_count)
    assert round_input.metadata_file is not None
    assert round_input.metadata_file.name == "round.yaml"
