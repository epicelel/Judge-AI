"""
Story 2.2 — Confirm or edit the detected structure.

The gate that stops a bad structure from costing a full 7-call run.
"""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cli import CONFIRM_PROMPT, cli, confirm_structure  # noqa: E402
from src.structure import SOURCE_EDITED, LabeledSpeech  # noqa: E402
from src.transcript import (  # noqa: E402
    DEFAULT_EDITOR,
    format_structured_transcript,
    parse_structured_transcript,
    resolve_editor,
)

STRUCTURED = """ROUND
Format: LD
Resolution: "Nukes are immoral"
Aff: Eliana | Neg: Marcus

=== 1AC (Aff, 4 words) ===

My value is morality.

=== 1NC (Neg, 5 words) ===

My value is life instead.
"""


class Answers:
    def __init__(self, *answers):
        self.queue = list(answers)
        self.prompts = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.queue.pop(0) if self.queue else ""


def never_edit(_text):
    raise AssertionError("editor must not open")


# --- Preview shows label, word count, speaker --------------------------


def test_preview_lists_label_words_and_speaker(tmp_path, monkeypatch):
    from src import ingest

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    folder = tmp_path / "New_Rounds" / "LD" / "mark_priya"
    folder.mkdir(parents=True)
    for name in ("1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR"):
        (folder / f"{name}.txt").write_text("word " * 60, encoding="utf-8")

    result = CliRunner().invoke(cli, ["new", str(folder)], input="\n\n\nquit\n")
    assert "1. 1AC    (~60 words, Aff)" in result.output
    assert "2. CX1    (~60 words, Both)" in result.output


# --- Y proceeds -------------------------------------------------------


@pytest.mark.parametrize("answer", ["", "y", "Y", "yes"])
def test_confirming_proceeds(answer):
    proceed, text = confirm_structure(
        STRUCTURED, ask=Answers(answer), launch_editor=never_edit
    )
    assert proceed is True
    assert text == STRUCTURED


def test_the_prompt_offers_all_three_choices():
    answers = Answers("")
    confirm_structure(STRUCTURED, ask=answers, launch_editor=never_edit)
    assert answers.prompts == ["Confirm? [Y/edit/quit]"]
    assert CONFIRM_PROMPT == "Confirm? [Y/edit/quit]"


# --- quit exits without spending --------------------------------------


@pytest.mark.parametrize("answer", ["quit", "q", "QUIT", "n"])
def test_quitting_stops_the_run(answer):
    proceed, _text = confirm_structure(
        STRUCTURED, ask=Answers(answer), launch_editor=never_edit
    )
    assert proceed is False


def test_quitting_writes_nothing_and_spends_nothing(tmp_path, monkeypatch):
    from src import ingest

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    folder = tmp_path / "New_Rounds" / "LD" / "mark_priya"
    folder.mkdir(parents=True)
    for name in ("1AC", "CX1", "1NC", "CX2", "1AR"):
        (folder / f"{name}.txt").write_text("word " * 60, encoding="utf-8")
    before = {p for p in tmp_path.rglob("*")}

    result = CliRunner().invoke(cli, ["new", str(folder)], input="\n\n\nquit\n")

    assert "Aborted. Nothing saved, no tokens spent." in result.output
    assert {p for p in tmp_path.rglob("*")} == before
    assert result.exit_code == 0  # a deliberate quit is not a failure


# --- edit opens $EDITOR and the edits are used ------------------------


def test_edit_opens_the_editor_and_adopts_the_result():
    edited = STRUCTURED.replace("=== 1NC (Neg, 5 words) ===", "=== 2NR (Neg) ===")
    opened = []

    def editor(text):
        opened.append(text)
        return edited

    proceed, text = confirm_structure(
        STRUCTURED, ask=Answers("edit", ""), launch_editor=editor
    )
    assert opened == [STRUCTURED]
    assert proceed is True
    assert "=== 2NR" in text


def test_editing_reprompts_so_a_mistake_can_be_corrected():
    """After editing, the user is asked again rather than dropped into judging."""
    answers = Answers("edit", "edit", "")
    calls = []

    def editor(text):
        calls.append(text)
        return text

    confirm_structure(STRUCTURED, ask=answers, launch_editor=editor)
    assert len(calls) == 2
    assert answers.prompts.count(CONFIRM_PROMPT) == 3


def test_editing_then_quitting_still_quits():
    proceed, _text = confirm_structure(
        STRUCTURED, ask=Answers("edit", "quit"), launch_editor=lambda text: text
    )
    assert proceed is False


def test_an_editor_that_returns_nothing_keeps_the_original():
    proceed, text = confirm_structure(
        STRUCTURED, ask=Answers("edit", ""), launch_editor=lambda _text: None
    )
    assert proceed is True and text == STRUCTURED


def test_edits_that_destroy_the_headers_are_rejected():
    """Without `=== LABEL ===` markers there are no speeches left to judge."""
    proceed, text = confirm_structure(
        STRUCTURED,
        ask=Answers("edit", ""),
        launch_editor=lambda _t: "I deleted everything by accident",
    )
    assert proceed is True
    assert text == STRUCTURED  # previous version retained


def test_unrecognized_answer_reprompts_rather_than_guessing():
    answers = Answers("maybe", "")
    proceed, _text = confirm_structure(
        STRUCTURED, ask=answers, launch_editor=never_edit
    )
    assert proceed is True
    assert len(answers.prompts) == 2


# --- Editor selection -------------------------------------------------


def test_editor_defaults_to_nano(monkeypatch):
    for name in ("JUDGEAI_EDITOR", "VISUAL", "EDITOR"):
        monkeypatch.delenv(name, raising=False)
    assert resolve_editor() == DEFAULT_EDITOR == "nano"


def test_editor_env_var_is_honoured(monkeypatch):
    monkeypatch.setenv("EDITOR", "vim")
    assert resolve_editor() == "vim"


def test_judgeai_editor_wins_over_editor(monkeypatch):
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setenv("JUDGEAI_EDITOR", "code -w")
    assert resolve_editor() == "code -w"


# --- Round-tripping an edited transcript -----------------------------


def test_parsing_recovers_every_speech():
    speeches = parse_structured_transcript(STRUCTURED)
    assert [s.label for s in speeches] == ["1AC", "1NC"]


def test_parsing_recovers_speech_text():
    speeches = parse_structured_transcript(STRUCTURED)
    assert speeches[0].path.read_text() == "My value is morality."


def test_parsed_speeches_are_marked_as_edited():
    assert all(s.source == SOURCE_EDITED for s in parse_structured_transcript(STRUCTURED))


def test_speaker_is_recovered_from_the_canonical_sequence():
    speeches = parse_structured_transcript("=== 2NR (Neg) ===\nsome text\n")
    assert speeches[0].speaker == "Neg" and speeches[0].position == 6


def test_a_moved_boundary_changes_the_speeches():
    """The point of `edit`: hand-moved boundaries become what gets judged."""
    edited = "=== 1AC (Aff) ===\nfirst half\n=== 1NC (Neg) ===\nsecond half\n"
    speeches = parse_structured_transcript(edited)
    assert speeches[0].path.read_text() == "first half"
    assert speeches[1].path.read_text() == "second half"


def test_empty_speeches_are_dropped():
    speeches = parse_structured_transcript("=== 1AC (Aff) ===\n\n=== 1NC (Neg) ===\ntext\n")
    assert [s.label for s in speeches] == ["1NC"]


def test_round_header_is_not_treated_as_a_speech():
    assert len(parse_structured_transcript(STRUCTURED)) == 2


def test_transcript_survives_a_format_parse_round_trip(tmp_path):
    path = tmp_path / "1AC.txt"
    path.write_text("My value is morality.", encoding="utf-8")
    original = [
        LabeledSpeech(path=path, label="1AC", speaker="Aff", position=1)
    ]
    rendered = format_structured_transcript(original)
    reparsed = parse_structured_transcript(rendered)
    assert reparsed[0].label == "1AC"
    assert reparsed[0].path.read_text() == "My value is morality."
