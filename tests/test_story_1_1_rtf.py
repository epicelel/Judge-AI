"""
Story 1.1, revised 2026-08-14 — `.rtf` is a first-class input.

RTF is TextEdit's default save format on macOS and the format transcripts
actually arrive in. The original file is never modified, and RTF markup must
never reach the model.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.documents import (  # noqa: E402
    DocumentError,
    is_transcript_file,
    read_transcript_text,
)
from src.ingest import IngestError, load_round_input  # noqa: E402
from src.transcript import read_speech_text  # noqa: E402

BODY = (
    "Resolved: Protecting the environment is more important than economic "
    "growth. My value is morality and my criterion is protecting life. "
    "Contention one: climate collapse is irreversible and threatens billions. "
    "I affirm and stand ready for cross-examination."
)

RTF = (
    "{\\rtf1\\ansi\\ansicpg1252\\cocoartf2870\n"
    "{\\fonttbl\\f0\\fswiss\\fcharset0 Helvetica;}\n"
    "{\\colortbl;\\red255\\green255\\blue255;}\n"
    "\\margl1440\\margr1440\\f0\\fs24 \\cf0 " + BODY + "}"
)


def write_rtf(folder: Path, name: str = "round.rtf") -> Path:
    path = folder / name
    path.write_text(RTF, encoding="utf-8")
    return path


@pytest.fixture
def inbox(tmp_path, monkeypatch) -> Path:
    from src import ingest

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    ld = tmp_path / "New_Rounds" / "LD"
    ld.mkdir(parents=True)
    return ld


# --- Recognition ------------------------------------------------------


@pytest.mark.parametrize("name", ["round.rtf", "round.RTF", "round.txt"])
def test_both_formats_are_recognized(name):
    assert is_transcript_file(Path(name))


@pytest.mark.parametrize("name", ["round.docx", "round.pdf", "round.mp3", "notes.md"])
def test_other_formats_are_not(name):
    assert not is_transcript_file(Path(name))


# --- Conversion -------------------------------------------------------


def test_rtf_is_converted_to_plain_text(tmp_path):
    text = read_transcript_text(write_rtf(tmp_path))
    assert "Protecting the environment" in text


def test_conversion_strips_every_control_word(tmp_path):
    """RTF markup reaching the model would produce a confidently wrong ballot."""
    text = read_transcript_text(write_rtf(tmp_path))
    for marker in ("\\rtf1", "\\ansi", "\\fonttbl", "\\margl", "cocoartf", "{", "}"):
        assert marker not in text, f"markup leaked: {marker}"


def test_the_original_rtf_is_never_modified(tmp_path):
    path = write_rtf(tmp_path)
    before = path.read_bytes()
    read_transcript_text(path)
    assert path.read_bytes() == before


def test_txt_is_read_unchanged(tmp_path):
    path = tmp_path / "round.txt"
    path.write_text(BODY, encoding="utf-8")
    assert read_transcript_text(path) == BODY


def test_a_file_claiming_rtf_but_not_rtf_is_rejected(tmp_path):
    path = tmp_path / "fake.rtf"
    path.write_text("this is just plain text, not RTF at all", encoding="utf-8")
    with pytest.raises(DocumentError):
        # textutil refuses it too; either path must raise rather than guess.
        read_transcript_text(path)


def test_the_pure_python_stripper_handles_escapes():
    from src.documents import _strip_rtf

    text = _strip_rtf("{\\rtf1\\ansi Hello\\par World\\tab done \\'41}")
    assert "Hello" in text and "World" in text
    assert "\n" in text
    assert "A" in text  # \'41 is hex for "A"


# --- Ingestion --------------------------------------------------------


def test_an_rtf_round_is_accepted_from_the_inbox(inbox):
    write_rtf(inbox)
    (round_input,) = load_round_input("LD")
    assert round_input.files[0].suffix == ".rtf"


def test_an_rtf_round_yields_converted_text(inbox):
    write_rtf(inbox)
    (round_input,) = load_round_input("LD")
    assert "Protecting the environment" in round_input.read_text()
    assert "\\rtf1" not in round_input.read_text()


def test_a_short_rtf_is_rejected_on_converted_length(inbox):
    """Markup must not count toward the 200-char floor."""
    padding = "\\margl1440\\margr1440\\vieww11520\\viewh8400\\viewkind0" * 20
    (inbox / "round.rtf").write_text(
        "{\\rtf1\\ansi" + padding + "\\f0\\fs24 \\cf0 too short}", encoding="utf-8"
    )
    with pytest.raises(IngestError) as caught:
        load_round_input("LD")
    assert "too short" in str(caught.value)


def test_a_docx_still_names_both_accepted_formats(tmp_path):
    path = tmp_path / "round.docx"
    path.write_text(BODY, encoding="utf-8")
    with pytest.raises(IngestError) as caught:
        load_round_input(str(path))
    assert str(caught.value) == (
        "Unsupported file type: .docx. "
        "v0.1 accepts .txt and .rtf files, or folders of them."
    )


def test_a_folder_may_mix_txt_and_rtf(inbox):
    folder = inbox / "mark_priya"
    folder.mkdir()
    for name in ("1AC.rtf", "CX1.txt", "1NC.rtf", "CX2.txt", "1AR.rtf"):
        if name.endswith(".rtf"):
            write_rtf(folder, name)
        else:
            (folder / name).write_text(BODY, encoding="utf-8")

    (round_input,) = load_round_input(str(folder), confirm=lambda _m: True)
    assert len(round_input.files) == 5
    assert {f.suffix for f in round_input.files} == {".rtf", ".txt"}


def test_rtf_speech_files_are_labeled_from_their_names(inbox):
    folder = inbox / "labeled"
    folder.mkdir()
    for name in ("2AR.rtf", "1AC.rtf", "1NC.rtf", "CX1.rtf", "CX2.rtf"):
        write_rtf(folder, name)
    (round_input,) = load_round_input(str(folder), confirm=lambda _m: True)
    assert [f.stem for f in round_input.files] == ["1AC", "CX1", "1NC", "CX2", "2AR"]


# --- Downstream: the assembled transcript must be clean --------------


def test_the_structured_transcript_contains_no_rtf_markup(tmp_path):
    from src.structure import LabeledSpeech
    from src.transcript import format_structured_transcript

    path = write_rtf(tmp_path, "1AC.rtf")
    text = format_structured_transcript(
        [LabeledSpeech(path=path, label="1AC", speaker="Aff", position=1)]
    )
    assert "Protecting the environment" in text
    assert "\\rtf1" not in text and "\\fonttbl" not in text


def test_read_speech_text_handles_in_memory_segments():
    """Detected and edited speeches aren't files; the dispatcher must cope."""
    from src.detection import _InMemorySegment

    assert read_speech_text(_InMemorySegment("1AC", "some text")) == "some text"


def test_word_counts_are_computed_on_converted_text(tmp_path):
    from src.structure import LabeledSpeech
    from src.transcript import summarize_speeches

    rows = summarize_speeches(
        [LabeledSpeech(path=write_rtf(tmp_path, "1AC.rtf"), label="1AC", speaker="Aff")]
    )
    assert rows[0]["words"] == len(BODY.split())
