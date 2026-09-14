"""
Story 1.4 — Archive input files after successful judging.

Inputs are moved (not copied) out of the inbox into Past_Rounds/<type>/ with a
searchable prefix. Every filesystem path here is under tmp_path.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.archive import archive_input_files, archive_target_name  # noqa: E402
from src.ingest import RoundInput  # noqa: E402
from src.storage import StorageError, parse_round_id  # noqa: E402

ROUND_ID = "847213.081126.possession-nuclear-weapons.eliana"
UNKNOWN_ROUND_ID = "999111.081126.unknown-resolution.unknown-aff"
BODY = "filler transcript text " * 40


@pytest.fixture
def inbox(tmp_path) -> Path:
    path = tmp_path / "New_Rounds" / "LD"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def archive_root(tmp_path) -> Path:
    return tmp_path / "Past_Rounds"


def single_file_round(inbox: Path, name: str = "nuclear_weapons.txt") -> RoundInput:
    path = inbox / name
    path.write_text(BODY, encoding="utf-8")
    return RoundInput(path=path, files=[path], is_folder=False, debate_format="LD")


def folder_round(inbox: Path, names=("1AC.txt", "CX1.txt", "1NC.txt")) -> RoundInput:
    folder = inbox / "mark_priya"
    folder.mkdir()
    files = []
    for name in names:
        path = folder / name
        path.write_text(BODY, encoding="utf-8")
        files.append(path)
    return RoundInput(path=folder, files=files, is_folder=True, debate_format="LD")


# --- Round_ID parsing, the source of archive filenames -----------------


def test_round_id_splits_into_four_parts():
    parts = parse_round_id(ROUND_ID)
    assert parts.numeric == "847213"
    assert parts.date == "081126"
    assert parts.resolution == "possession-nuclear-weapons"
    assert parts.aff == "eliana"


def test_archive_stem_omits_the_numeric_prefix():
    assert parse_round_id(ROUND_ID).archive_stem == (
        "081126.possession-nuclear-weapons.eliana"
    )


def test_malformed_round_id_is_rejected():
    with pytest.raises(StorageError):
        parse_round_id("nope")


# --- Naming (Story 1.4 filename format) -------------------------------


def test_single_file_target_name():
    name = archive_target_name(ROUND_ID, Path("nuclear_weapons.txt"), is_folder=False)
    assert name == "081126.possession-nuclear-weapons.eliana.txt"


def test_folder_file_target_name_keeps_the_speech_label():
    name = archive_target_name(ROUND_ID, Path("1AC.txt"), is_folder=True)
    assert name == "081126.possession-nuclear-weapons.eliana.1AC.txt"


def test_disambiguated_name_inserts_the_six_digit_id():
    name = archive_target_name(
        ROUND_ID, Path("nuclear_weapons.txt"), is_folder=False, disambiguate=True
    )
    assert name == "081126.possession-nuclear-weapons.eliana.847213.txt"


def test_missing_metadata_produces_unknown_slugs():
    name = archive_target_name(UNKNOWN_ROUND_ID, Path("r.txt"), is_folder=False)
    assert name == "081126.unknown-resolution.unknown-aff.txt"


# --- Given a successful round, inputs are moved not copied ------------


def test_single_file_is_moved_into_the_archive(inbox, archive_root):
    round_input = single_file_round(inbox)
    source = round_input.files[0]

    result = archive_input_files(round_input, ROUND_ID, archive_root=archive_root)

    assert result.ok is True
    assert not source.exists()  # moved, not copied
    assert (
        archive_root / "LD" / "081126.possession-nuclear-weapons.eliana.txt"
    ).exists()


def test_archived_content_is_intact(inbox, archive_root):
    round_input = single_file_round(inbox)
    archive_input_files(round_input, ROUND_ID, archive_root=archive_root)
    archived = archive_root / "LD" / "081126.possession-nuclear-weapons.eliana.txt"
    assert archived.read_text(encoding="utf-8") == BODY


def test_every_speech_file_in_a_folder_is_renamed_with_the_prefix(inbox, archive_root):
    round_input = folder_round(inbox)
    archive_input_files(round_input, ROUND_ID, archive_root=archive_root)
    names = sorted(p.name for p in (archive_root / "LD").iterdir())
    assert names == [
        "081126.possession-nuclear-weapons.eliana.1AC.txt",
        "081126.possession-nuclear-weapons.eliana.1NC.txt",
        "081126.possession-nuclear-weapons.eliana.CX1.txt",
    ]


def test_inbox_is_left_empty_after_archiving_a_folder(inbox, archive_root):
    """The point of an inbox is that it empties."""
    round_input = folder_round(inbox)
    archive_input_files(round_input, ROUND_ID, archive_root=archive_root)
    assert not round_input.path.exists()
    assert list(inbox.iterdir()) == []


def test_archive_directory_is_created_on_demand(inbox, archive_root):
    assert not archive_root.exists()
    archive_input_files(single_file_round(inbox), ROUND_ID, archive_root=archive_root)
    assert (archive_root / "LD").is_dir()


def test_archive_is_partitioned_by_debate_type(inbox, archive_root):
    round_input = single_file_round(inbox)
    round_input.debate_format = "PF"
    archive_input_files(round_input, ROUND_ID, archive_root=archive_root)
    assert (archive_root / "PF").is_dir()


def test_result_reports_what_was_moved(inbox, archive_root):
    round_input = folder_round(inbox)
    result = archive_input_files(round_input, ROUND_ID, archive_root=archive_root)
    assert result.count == 3
    assert all(target.exists() for _source, target in result.moved)


# --- The round.yaml sidecar travels with the round --------------------


def test_sidecar_is_archived_alongside_the_transcripts(inbox, archive_root):
    round_input = folder_round(inbox)
    sidecar = round_input.path / "round.yaml"
    sidecar.write_text('aff: "Eliana"\n', encoding="utf-8")
    round_input.metadata_file = sidecar

    archive_input_files(round_input, ROUND_ID, archive_root=archive_root)

    assert not sidecar.exists()
    assert (
        archive_root / "LD" / "081126.possession-nuclear-weapons.eliana.round.yaml"
    ).exists()


def test_absent_sidecar_is_not_a_problem(inbox, archive_root):
    round_input = folder_round(inbox)
    round_input.metadata_file = round_input.path / "does_not_exist.yaml"
    assert archive_input_files(round_input, ROUND_ID, archive_root=archive_root).ok


# --- Given the target name is taken, disambiguate ---------------------


def test_existing_archive_name_is_not_overwritten(inbox, archive_root):
    """Same date, resolution, and speaker as an earlier round."""
    existing = archive_root / "LD" / "081126.possession-nuclear-weapons.eliana.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("an earlier round", encoding="utf-8")

    archive_input_files(single_file_round(inbox), ROUND_ID, archive_root=archive_root)

    assert existing.read_text(encoding="utf-8") == "an earlier round"
    assert (
        archive_root / "LD" / "081126.possession-nuclear-weapons.eliana.847213.txt"
    ).exists()


def test_collision_in_folder_mode_also_disambiguates(inbox, archive_root):
    existing = archive_root / "LD" / "081126.possession-nuclear-weapons.eliana.1AC.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("an earlier 1AC", encoding="utf-8")

    archive_input_files(folder_round(inbox), ROUND_ID, archive_root=archive_root)

    assert existing.read_text(encoding="utf-8") == "an earlier 1AC"
    assert (
        archive_root / "LD" / "081126.possession-nuclear-weapons.eliana.847213.1AC.txt"
    ).exists()


# --- Given archiving fails, warn without crashing --------------------


def test_unwritable_archive_reports_a_warning_instead_of_raising(inbox, tmp_path):
    """A paid-for run must not be reported as a failure over a move error."""
    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    round_input = single_file_round(inbox)

    result = archive_input_files(round_input, ROUND_ID, archive_root=blocker)

    assert result.ok is False
    assert "Judged successfully but could not archive input files" in result.warning
    assert "Manually move them from" in result.warning


def test_inputs_survive_a_failed_archive(inbox, tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    round_input = single_file_round(inbox)

    archive_input_files(round_input, ROUND_ID, archive_root=blocker)

    assert round_input.files[0].exists()  # still retrievable from the inbox


def test_warning_names_the_location_to_recover_from(inbox, tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    round_input = folder_round(inbox)
    result = archive_input_files(round_input, ROUND_ID, archive_root=blocker)
    assert str(round_input.path) in result.warning


# --- Given judging failed, nothing is archived -----------------------


def test_inputs_are_archived_after_a_successful_run(tmp_path, monkeypatch):
    """
    Was: asserted the inbox stayed untouched because judging did not exist yet.
    Flipped at Increment 12, when archiving was wired to a real run.
    """
    from click.testing import CliRunner

    from src import ingest, storage
    from src.archive import ARCHIVE_ROOT  # noqa: F401  (imported for clarity)
    from src.cli import cli
    from tests.conftest import FakeBedrockClient

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    monkeypatch.setattr(ingest, "ARCHIVE_ROOT", tmp_path / "Past_Rounds")
    monkeypatch.setattr("src.archive.ARCHIVE_ROOT", tmp_path / "Past_Rounds")
    monkeypatch.setattr(storage, "DEFAULT_BALLOTS_ROOT", tmp_path / "Ballots")

    folder = tmp_path / "New_Rounds" / "LD" / "mark_priya"
    folder.mkdir(parents=True)
    for name in ("1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR"):
        (folder / f"{name}.txt").write_text("word " * 60, encoding="utf-8")

    ballot = (
        "WINNER: AFF\nLEAN: clear\nRFD: Short reason.\n"
        "SPEAKER POINTS: Aff 28 / Neg 27\nKEY VOTING ISSUES:\n1. Something.\n"
    )
    monkeypatch.setattr(
        "src.cli.build_client", lambda **_kw: FakeBedrockClient(responses=[ballot])
    )

    result = CliRunner().invoke(
        cli, ["new", str(folder), "--personas", "lay"], input="\n\n\ny\n"
    )

    assert result.exit_code == 0
    assert not folder.exists()  # inbox emptied
    archived = sorted(p.name for p in (tmp_path / "Past_Rounds" / "LD").iterdir())
    assert len(archived) == 7
    assert all(name.endswith(".txt") for name in archived)


def test_inputs_are_kept_in_the_inbox_when_a_paradigm_fails(tmp_path, monkeypatch):
    """Story 1.4: a partial run must stay re-runnable without a file hunt."""
    from click.testing import CliRunner

    from src import ingest, storage
    from src.cli import cli
    from tests.conftest import FakeBedrockClient

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    monkeypatch.setattr("src.archive.ARCHIVE_ROOT", tmp_path / "Past_Rounds")
    monkeypatch.setattr(storage, "DEFAULT_BALLOTS_ROOT", tmp_path / "Ballots")

    folder = tmp_path / "New_Rounds" / "LD" / "mark_priya"
    folder.mkdir(parents=True)
    for name in ("1AC", "CX1", "1NC", "CX2", "1AR"):
        (folder / f"{name}.txt").write_text("word " * 60, encoding="utf-8")

    monkeypatch.setattr(
        "src.cli.build_client",
        lambda **_kw: FakeBedrockClient(responses=["x"], fail_times=99),
    )

    CliRunner().invoke(
        cli, ["new", str(folder), "--personas", "lay"], input="\n\n\ny\n"
    )

    assert folder.exists()
    assert len(list(folder.iterdir())) == 5
    assert not (tmp_path / "Past_Rounds").exists()
