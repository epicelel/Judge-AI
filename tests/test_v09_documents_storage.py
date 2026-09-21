from pathlib import Path

from src import ingest
from src.storage import (
    CANONICAL_BALLOTS_ROOT,
    USER_DATA_ROOT,
    import_legacy_user_data,
)


def test_default_user_data_root_is_documents():
    assert USER_DATA_ROOT == Path.home() / "Documents" / "JudgeAI"
    assert CANONICAL_BALLOTS_ROOT == USER_DATA_ROOT / "Ballots"
    assert ingest.JUDGEAI_ROOT == Path.home() / "Documents" / "JudgeAI"


def test_legacy_import_copies_known_user_data_without_overwriting(tmp_path: Path):
    legacy = tmp_path / "Desktop" / "JudgeAI"
    current = tmp_path / "Documents" / "JudgeAI"

    old_ballot = legacy / "Ballots" / "round-old" / "metadata.json"
    old_ballot.parent.mkdir(parents=True)
    old_ballot.write_text('{"old": true}', encoding="utf-8")

    old_archive = legacy / "Past_Rounds" / "LD" / "round.txt"
    old_archive.parent.mkdir(parents=True)
    old_archive.write_text("legacy transcript", encoding="utf-8")

    old_inbox = legacy / "New_Rounds" / "LD" / "next.txt"
    old_inbox.parent.mkdir(parents=True)
    old_inbox.write_text("next round", encoding="utf-8")

    existing = current / "Ballots" / "round-old" / "metadata.json"
    existing.parent.mkdir(parents=True)
    existing.write_text('{"new": true}', encoding="utf-8")

    copied = import_legacy_user_data(legacy, current)

    # Existing destination content wins; migration never overwrites it.
    assert existing.read_text(encoding="utf-8") == '{"new": true}'

    # Other known user-data folders are imported.
    assert (current / "Past_Rounds" / "LD" / "round.txt").read_text(
        encoding="utf-8"
    ) == "legacy transcript"
    assert (current / "New_Rounds" / "LD" / "next.txt").read_text(
        encoding="utf-8"
    ) == "next round"

    # Old files remain in place as a backup.
    assert old_ballot.exists()
    assert old_archive.exists()
    assert old_inbox.exists()

    assert copied == 2


def test_legacy_import_ignores_unrelated_desktop_judgeai_files(tmp_path: Path):
    legacy = tmp_path / "Desktop" / "JudgeAI"
    current = tmp_path / "Documents" / "JudgeAI"

    unrelated = legacy / "private-source-code" / "secret.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("do not import", encoding="utf-8")

    copied = import_legacy_user_data(legacy, current)

    assert copied == 0
    assert not (current / "private-source-code").exists()
    assert unrelated.exists()
