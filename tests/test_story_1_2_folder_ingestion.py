"""
Story 1.2 — Judge a round from a folder of speech files, with debate-type-aware
file-count validation.

Each test name restates one Given/When/Then. The confirm prompt is injected, so
nothing here blocks on stdin.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import ingest  # noqa: E402
from src.ingest import (  # noqa: E402
    FILE_COUNT_RULES,
    IngestAborted,
    IngestError,
    load_round_input,
    validate_file_count,
)

BODY = (
    "Resolved: The possession of nuclear weapons is immoral. My value is "
    "morality and my criterion is preventing death. Contention one: nuclear "
    "weapons create existential risk through accident and miscalculation. "
    "I affirm and stand ready for cross-examination."
)

LD_SPEECHES = ("1AC.txt", "CX1.txt", "1NC.txt", "CX2.txt", "1AR.txt", "2NR.txt", "2AR.txt")


@pytest.fixture
def inbox(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "JudgeAI" / "New_Rounds"
    monkeypatch.setattr(ingest, "INBOX_ROOT", root)
    ld = root / "LD"
    ld.mkdir(parents=True)
    return ld


def make_folder(inbox: Path, name: str, filenames) -> Path:
    folder = inbox / name
    folder.mkdir()
    for filename in filenames:
        (folder / filename).write_text(BODY, encoding="utf-8")
    return folder


def refuse(_message: str) -> bool:
    return False


def accept(_message: str) -> bool:
    return True


class RecordingConfirm:
    """Captures prompt text so tests can assert exact wording."""

    def __init__(self, answer: bool = True):
        self.answer = answer
        self.messages = []

    def __call__(self, message: str) -> bool:
        self.messages.append(message)
        return self.answer


# --- Given a folder of 7 files, when I pick it --------------------------


def test_seven_file_ld_folder_is_read_as_one_speech_per_file(inbox):
    folder = make_folder(inbox, "mark_priya", LD_SPEECHES)
    (round_input,) = load_round_input(str(folder), confirm=refuse)
    assert round_input.is_folder is True
    assert len(round_input.files) == 7


def test_picking_a_folder_from_the_inbox_loads_it(inbox):
    make_folder(inbox, "mark_priya", LD_SPEECHES)
    (round_input,) = load_round_input("LD", confirm=refuse)
    assert round_input.name == "mark_priya"


def test_each_file_is_treated_as_a_separate_speech(inbox):
    folder = make_folder(inbox, "mark_priya", LD_SPEECHES)
    (round_input,) = load_round_input(str(folder), confirm=refuse)
    assert len({f.name for f in round_input.files}) == 7


# --- Given non-.txt files in the folder --------------------------------


def test_stray_non_transcript_files_are_ignored_silently(inbox):
    folder = make_folder(inbox, "mark_priya", LD_SPEECHES)
    (folder / ".DS_Store").write_bytes(b"\x00\x01")
    (folder / "recording.mp3").write_bytes(b"\x00")
    (folder / "notes.docx").write_text("x")
    (round_input,) = load_round_input(str(folder), confirm=refuse)
    assert len(round_input.files) == 7


def test_yaml_metadata_is_kept_not_ignored(inbox):
    folder = make_folder(inbox, "mark_priya", LD_SPEECHES)
    (folder / "round.yaml").write_text("resolution: test\n")
    (round_input,) = load_round_input(str(folder), confirm=refuse)
    assert round_input.metadata_file.name == "round.yaml"
    assert len(round_input.files) == 7  # the yaml is not counted as a speech


def test_non_transcript_files_do_not_count_toward_the_file_count(inbox):
    """5 .txt + 4 junk files must not trip the max-7 warning."""
    folder = make_folder(inbox, "mark_priya", LD_SPEECHES[:5])
    for junk in ("a.mp3", "b.docx", "c.pdf", "d.m4a"):
        (folder / junk).write_bytes(b"\x00")
    confirm = RecordingConfirm()
    load_round_input(str(folder), confirm=confirm)
    assert confirm.messages == []


# --- Given fewer files than the minimum -------------------------------


def test_three_files_for_ld_prompts_with_the_minimum_message(inbox):
    folder = make_folder(inbox, "partial", LD_SPEECHES[:3])
    confirm = RecordingConfirm(answer=True)
    load_round_input(str(folder), confirm=confirm)
    assert confirm.messages == [
        "Only found 3 speech files for LD. "
        "Minimum is 5 (all debate speeches). Proceed anyway?"
    ]


def test_declining_the_minimum_prompt_aborts(inbox):
    folder = make_folder(inbox, "partial", LD_SPEECHES[:3])
    with pytest.raises(IngestAborted):
        load_round_input(str(folder), confirm=refuse)


def test_accepting_the_minimum_prompt_proceeds(inbox):
    folder = make_folder(inbox, "partial", LD_SPEECHES[:3])
    (round_input,) = load_round_input(str(folder), confirm=accept)
    assert len(round_input.files) == 3


def test_single_file_folder_prompts_rather_than_failing(inbox):
    folder = make_folder(inbox, "just_one", ("1AC.txt",))
    confirm = RecordingConfirm()
    load_round_input(str(folder), confirm=confirm)
    assert "Only found 1 speech files for LD" in confirm.messages[0]


# --- Given more files than the maximum --------------------------------


def test_ten_files_for_ld_prompts_with_the_maximum_message(inbox):
    folder = make_folder(inbox, "too_many", [f"speech_{i:02d}.txt" for i in range(10)])
    confirm = RecordingConfirm(answer=True)
    load_round_input(str(folder), confirm=confirm)
    assert confirm.messages == [
        "Found 10 speech files for LD. "
        "Maximum expected is 7 (5 debate speeches + 2 cross-ex). Proceed anyway?"
    ]


def test_declining_the_maximum_prompt_aborts(inbox):
    folder = make_folder(inbox, "too_many", [f"speech_{i:02d}.txt" for i in range(10)])
    with pytest.raises(IngestAborted):
        load_round_input(str(folder), confirm=refuse)


def test_accepting_the_maximum_prompt_proceeds(inbox):
    folder = make_folder(inbox, "too_many", [f"speech_{i:02d}.txt" for i in range(10)])
    (round_input,) = load_round_input(str(folder), confirm=accept)
    assert len(round_input.files) == 10


# --- Given a count between min and max -------------------------------


@pytest.mark.parametrize("count", [5, 6, 7])
def test_counts_within_the_ld_range_never_prompt(inbox, count):
    folder = make_folder(inbox, f"round_{count}", LD_SPEECHES[:count])
    confirm = RecordingConfirm()
    (round_input,) = load_round_input(str(folder), confirm=confirm)
    assert confirm.messages == []
    assert len(round_input.files) == count


def test_exactly_at_the_minimum_does_not_prompt(inbox):
    folder = make_folder(inbox, "five", LD_SPEECHES[:5])
    confirm = RecordingConfirm()
    load_round_input(str(folder), confirm=confirm)
    assert confirm.messages == []


def test_exactly_at_the_maximum_does_not_prompt(inbox):
    folder = make_folder(inbox, "seven", LD_SPEECHES)
    confirm = RecordingConfirm()
    load_round_input(str(folder), confirm=confirm)
    assert confirm.messages == []


# --- Mode A is exempt -------------------------------------------------


def test_single_file_mode_is_never_count_validated(inbox):
    """One .txt file is a whole round, not one speech."""
    path = inbox / "round.txt"
    path.write_text(BODY, encoding="utf-8")
    confirm = RecordingConfirm()
    load_round_input(str(path), confirm=confirm)
    assert confirm.messages == []


# --- The rules table itself ------------------------------------------


def test_ld_rule_matches_the_spec():
    rule = FILE_COUNT_RULES["LD"]
    assert (rule.minimum, rule.maximum) == (5, 7)


@pytest.mark.parametrize(
    "fmt,minimum,maximum",
    [("LD", 5, 7), ("PF", 6, 9), ("Worlds", 8, 8), ("Congress", 4, 12), ("Parli", 6, 6)],
)
def test_every_documented_format_has_the_specified_range(fmt, minimum, maximum):
    """User Stories §0.1 table. Only LD is exercised in v0.1."""
    rule = FILE_COUNT_RULES[fmt]
    assert (rule.minimum, rule.maximum) == (minimum, maximum)


def test_pf_uses_its_own_range_not_lds():
    confirm = RecordingConfirm()
    validate_file_count("PF", 7, confirm=confirm)  # inside PF's 6-9
    assert confirm.messages == []


def test_seven_files_would_warn_for_worlds_but_not_for_ld():
    ld = RecordingConfirm()
    validate_file_count("LD", 7, confirm=ld)
    worlds = RecordingConfirm()
    validate_file_count("Worlds", 7, confirm=worlds)
    assert ld.messages == []
    assert "Only found 7 speech files for Worlds" in worlds.messages[0]


def test_unknown_format_is_not_count_validated():
    confirm = RecordingConfirm()
    validate_file_count("Klingon", 99, confirm=confirm)
    assert confirm.messages == []


def test_format_name_is_case_insensitive_in_the_message():
    confirm = RecordingConfirm()
    validate_file_count("ld", 2, confirm=confirm)
    assert "for LD." in confirm.messages[0]


# --- Interaction with other flags ------------------------------------


def test_all_flag_validates_each_folder_separately(inbox):
    make_folder(inbox, "good", LD_SPEECHES)
    make_folder(inbox, "short", LD_SPEECHES[:2])
    confirm = RecordingConfirm(answer=True)
    rounds = load_round_input("LD", select_all=True, confirm=confirm)
    assert len(rounds) == 2
    assert len(confirm.messages) == 1  # only the short folder prompted
    assert "Only found 2 speech files" in confirm.messages[0]


def test_folder_with_no_transcripts_still_reports_that_first(inbox):
    """An empty folder is a different problem from a wrong count."""
    folder = inbox / "empty"
    folder.mkdir()
    with pytest.raises(IngestError) as caught:
        load_round_input(str(folder), confirm=accept)
    assert "No speech files found" in str(caught.value)


def test_count_is_validated_before_files_are_read(inbox):
    """Declining must short-circuit before per-file validation runs."""
    folder = inbox / "partial"
    folder.mkdir()
    (folder / "1AC.txt").write_text("too short to pass validation")
    with pytest.raises(IngestAborted):
        load_round_input(str(folder), confirm=refuse)


# --- The prompt must never hang, and must never reject piped answers ----


def test_piped_answers_are_read_not_rejected(inbox):
    """
    `echo y | judge.py new folder/` has to work.

    An isatty() guard would refuse this, and prompting with no fallback would
    hang forever — the failure mode of the previous build.
    """
    from click.testing import CliRunner

    from src.cli import cli

    folder = make_folder(inbox, "partial", LD_SPEECHES[:3])
    result = CliRunner().invoke(cli, ["new", str(folder)], input="y\n")
    assert result.exit_code == 0
    assert "Loaded partial" in result.output


def test_piped_no_aborts_cleanly(inbox):
    from click.testing import CliRunner

    from src.cli import cli

    folder = make_folder(inbox, "partial", LD_SPEECHES[:3])
    result = CliRunner().invoke(cli, ["new", str(folder)], input="n\n")
    assert result.exit_code == 0  # a deliberate decline is not a failure
    assert "Aborted." in result.output


def test_absent_input_names_the_yes_flag_instead_of_hanging(inbox):
    from click.testing import CliRunner

    from src.cli import cli

    folder = make_folder(inbox, "partial", LD_SPEECHES[:3])
    result = CliRunner().invoke(cli, ["new", str(folder)], input="")
    assert "Re-run with --yes" in result.output


def test_yes_flag_confirms_without_asking(inbox):
    from click.testing import CliRunner

    from src.cli import cli

    folder = make_folder(inbox, "partial", LD_SPEECHES[:3])
    result = CliRunner().invoke(cli, ["new", str(folder), "--yes"])
    assert result.exit_code == 0
    assert "auto-confirmed via --yes" in result.output  # never silent
    assert "Loaded partial" in result.output
