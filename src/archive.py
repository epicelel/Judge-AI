"""
Archiving processed inputs (Story 1.4).

After a round is judged successfully, its input files are **moved** out of the
inbox into `~/Desktop/JudgeAI/Past_Rounds/<debate_type>/`, renamed with a
searchable prefix so the archive can be scanned by date, resolution, and
speaker:

    single file:      081126.possession-nuclear-weapons.eliana.txt
    folder contents:  081126.possession-nuclear-weapons.eliana.1AC.txt
                      081126.possession-nuclear-weapons.eliana.CX1.txt

Moving (not copying) is deliberate — it leaves the inbox empty and ready for
the next round, which is the whole point of having an inbox.

Archiving happens only after judging succeeds. Failure to archive must never
lose a paid-for run, so every filesystem error is caught and reported as a
warning rather than raised.
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .ingest import ARCHIVE_ROOT, RoundInput, normalize_debate_format
from .storage import parse_round_id


@dataclass
class ArchiveResult:
    """Outcome of an archive attempt. Never raises; inspect `ok`."""

    ok: bool
    archive_dir: Path
    moved: List[Tuple[Path, Path]] = field(default_factory=list)
    warning: Optional[str] = None

    @property
    def count(self) -> int:
        return len(self.moved)


def archive_target_name(
    round_id: str,
    original: Path,
    is_folder: bool,
    disambiguate: bool = False,
) -> str:
    """
    Build the archived filename for one input file.

    Folder inputs keep their original stem as a suffix so individual speeches
    stay identifiable. `disambiguate` inserts the Round_ID's 6-digit prefix,
    used when the target name is already taken.
    """
    parts = parse_round_id(round_id)
    pieces = [parts.archive_stem]
    if disambiguate:
        pieces.append(parts.numeric)
    if is_folder:
        pieces.append(original.stem)
    return ".".join(pieces) + original.suffix


def archive_input_files(
    round_input: RoundInput,
    round_id: str,
    archive_root: Optional[Path] = None,
) -> ArchiveResult:
    """
    Move a judged round's inputs into the archive (Story 1.4).

    Call this only after judging has succeeded. Returns an ArchiveResult; on
    failure `ok` is False and `warning` carries a message telling the user where
    the files still are, so a successful run is never reported as a failure.
    """
    root = Path(archive_root) if archive_root else ARCHIVE_ROOT
    archive_dir = root / normalize_debate_format(round_input.debate_format)

    # The sidecar travels with the round: metadata is worth keeping next to the
    # transcript it describes.
    sources = list(round_input.files)
    if round_input.metadata_file and round_input.metadata_file.exists():
        sources.append(round_input.metadata_file)

    moved: List[Tuple[Path, Path]] = []
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)

        for source in sources:
            target = archive_dir / archive_target_name(
                round_id, source, round_input.is_folder
            )
            if target.exists():
                # Same date, resolution, and speaker as an earlier round: fall
                # back to the Round_ID's 6-digit prefix rather than overwrite.
                target = archive_dir / archive_target_name(
                    round_id, source, round_input.is_folder, disambiguate=True
                )
            shutil.move(str(source), str(target))
            moved.append((source, target))

        # A folder input leaves an empty directory behind; remove it so the
        # inbox is genuinely clear. Anything unexpected still inside is left
        # alone, along with the folder.
        if round_input.is_folder and round_input.path.is_dir():
            if not any(round_input.path.iterdir()):
                round_input.path.rmdir()

    except OSError as exc:
        return ArchiveResult(
            ok=False,
            archive_dir=archive_dir,
            moved=moved,
            warning=(
                f"Judged successfully but could not archive input files: {exc}. "
                f"Manually move them from {round_input.path} when possible."
            ),
        )

    return ArchiveResult(ok=True, archive_dir=archive_dir, moved=moved)
