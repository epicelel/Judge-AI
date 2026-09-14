"""
Round input loading (Epic 1).

Two ingestion modes (MVP §4.2):
  Mode A — a single .txt file holding the whole round.
  Mode B — a folder of .txt files, one per speech.

Either can be named explicitly or auto-picked from the inbox for a debate type.
No transcript text is ever pasted in; callers supply paths only.

Story 1.1 implemented here. Folder file-count validation (1.2), metadata
(1.3), and archiving (1.4) build on the same primitives.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .documents import (
    DocumentError,
    TRANSCRIPT_SUFFIXES,
    is_transcript_file,
    read_transcript_text,
)
from .structure import order_speech_files

# Filesystem conventions (User Stories §0.1, with the inbox on the Desktop
# alongside Ballots and Past_Rounds so all three live in one place).
JUDGEAI_ROOT = Path.home() / "Desktop" / "JudgeAI"
INBOX_ROOT = JUDGEAI_ROOT / "New_Rounds"
ARCHIVE_ROOT = JUDGEAI_ROOT / "Past_Rounds"

DEBATE_TYPES = ("LD", "PF", "Worlds", "Congress", "Parli")

# Accepted transcript formats live in documents.py; .rtf is converted on read.
METADATA_SUFFIXES = (".yaml", ".yml")

# A round shorter than this isn't a transcript — it's a stray note or a header.
MIN_TRANSCRIPT_CHARS = 200


@dataclass(frozen=True)
class FileCountRule:
    """
    Expected speech-file count for a debate type (Story 1.2).

    The minimum is the debate's speeches; the maximum adds cross-examination
    segments. Counts outside the range only warn — the user can always proceed,
    since partial recordings are a normal thing to want to judge.
    """

    minimum: int
    maximum: int
    max_note: str
    min_note: str = "all debate speeches"


# v0.1 enforces LD only; the rest are specified for v0.5 (User Stories §0.1).
FILE_COUNT_RULES = {
    "LD": FileCountRule(5, 7, "5 debate speeches + 2 cross-ex"),
    "PF": FileCountRule(6, 9, "6 core speeches + 3 crossfire"),
    "Worlds": FileCountRule(8, 8, "8 speeches, no cross-ex"),
    "Congress": FileCountRule(4, 12, "solo speeches vary in count"),
    "Parli": FileCountRule(6, 6, "6 speeches, POIs inline"),
}


class IngestError(Exception):
    """A problem with the user's input that they can correct."""


class IngestAborted(IngestError):
    """The user declined a confirmation prompt. Not an error condition."""


@dataclass
class RoundInput:
    """One round's worth of input files, ready for structure detection."""

    path: Path                      # the file or folder the user chose
    files: List[Path]               # .txt speech files, in order
    is_folder: bool
    debate_format: str = "LD"
    metadata_file: Optional[Path] = field(default=None)  # round.yaml, if present

    @property
    def name(self) -> str:
        return self.path.name

    def read_text(self) -> str:
        """Concatenate every input file, in order, converting RTF as needed."""
        return "\n\n".join(read_transcript_text(f) for f in self.files)


def inbox_for(debate_format: str) -> Path:
    """The inbox folder for a debate type, e.g. ~/Desktop/JudgeAI/New_Rounds/LD/."""
    return INBOX_ROOT / normalize_debate_format(debate_format)


def normalize_debate_format(value: str) -> str:
    """Map user input to a canonical debate type name, case-insensitively."""
    for known in DEBATE_TYPES:
        if value.strip().lower() == known.lower():
            return known
    return value.strip()


def is_debate_format(value: str) -> bool:
    """True when the argument names a debate type rather than a path."""
    return any(value.strip().lower() == known.lower() for known in DEBATE_TYPES)


def _natural_key(path: Path):
    """
    Sort key that orders speech_2 before speech_10.

    Plain lexicographic sorting puts "speech_10" first, which would scramble
    speech order in Mode B.
    """
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r"(\d+)", path.name)
    ]


def _is_hidden(path: Path) -> bool:
    """Skip dotfiles — .DS_Store in particular shows up constantly on macOS."""
    return path.name.startswith(".")


def transcript_files_in(folder: Path) -> List[Path]:
    """Every .txt file in a folder, in speech order, ignoring hidden files."""
    return sorted(
        (
            p for p in folder.iterdir()
            if p.is_file()
            and is_transcript_file(p)
            and not _is_hidden(p)
        ),
        key=_natural_key,
    )


def metadata_file_in(folder: Path, stem: Optional[str] = None) -> Optional[Path]:
    """
    The round.yaml sidecar for a round, if one exists (read in Story 1.3).

    When `stem` is given (Mode A), a sidecar named after the transcript wins —
    `nuclear_weapons.yaml` for `nuclear_weapons.txt`. Without that rule, a
    loose .txt file in the inbox would silently adopt the round.yaml belonging
    to a neighbouring round.
    """
    candidates = sorted(
        (
            p for p in folder.iterdir()
            if p.is_file()
            and p.suffix.lower() in METADATA_SUFFIXES
            and not _is_hidden(p)
        ),
        key=_natural_key,
    )
    if stem:
        for candidate in candidates:
            if candidate.stem.lower() == stem.lower():
                return candidate
    return candidates[0] if candidates else None


def list_inbox_items(debate_format: str) -> List[Path]:
    """
    Candidate rounds sitting in the inbox: .txt files and subfolders.

    A subfolder is a Mode B round (one file per speech); a .txt file is a
    Mode A round.
    """
    inbox = inbox_for(debate_format)
    if not inbox.exists():
        return []

    items = [
        p for p in inbox.iterdir()
        if not _is_hidden(p)
        and (p.is_dir() or is_transcript_file(p))
    ]
    # Folders first, then files; each group in natural order. Matches how the
    # picker reads: grouped by kind rather than interleaved.
    return sorted(items, key=lambda p: (p.is_file(), _natural_key(p)))


def validate_transcript_file(path: Path) -> None:
    """
    Reject inputs that can't be a round (Story 1.1).

    Error text is quoted verbatim from the story's acceptance criteria.
    """
    if not is_transcript_file(path):
        raise IngestError(
            f"Unsupported file type: {path.suffix}. "
            f"v0.1 accepts .txt and .rtf files, or folders of them."
        )

    try:
        # RTF is converted here, so the length floor is measured on real text
        # rather than on markup.
        content = read_transcript_text(path)
    except DocumentError as exc:
        raise IngestError(str(exc)) from exc

    if len(content.strip()) < MIN_TRANSCRIPT_CHARS:
        raise IngestError(
            f"Transcript too short (<{MIN_TRANSCRIPT_CHARS} chars). "
            f"Not a real round."
        )


def _default_confirm(message: str) -> bool:
    """
    Default [y/N] prompt, defaulting to No.

    Piped answers (`echo y | judge.py ...`) are read normally. Only when there
    is no answer to be had — closed stdin, captured stdin, EOF — do we refuse
    with a message naming --yes. Checking isatty() instead would reject piped
    input, and prompting blindly would hang forever, which is what the previous
    build did.
    """
    import click

    try:
        return click.confirm(message, default=False, err=True)
    except (click.Abort, EOFError, OSError) as exc:
        raise IngestError(
            f"{message}\n"
            f"Cannot prompt: no input available. "
            f"Re-run with --yes to accept prompts automatically."
        ) from exc


def validate_file_count(
    debate_format: str,
    file_count: int,
    confirm: Optional[Callable[[str], bool]] = None,
) -> None:
    """
    Warn when a folder's speech-file count doesn't fit the debate type (Story 1.2).

    Counts within [minimum, maximum] pass silently. Anything outside prompts,
    because a partial recording is a legitimate thing to want judged — so this
    is a confirmation, not a rejection. Declining raises IngestAborted.

    Debate types with no rule (an unrecognized --format) are not validated.
    """
    fmt = normalize_debate_format(debate_format)
    rule = FILE_COUNT_RULES.get(fmt)
    if rule is None or rule.minimum <= file_count <= rule.maximum:
        return

    # Message text is quoted verbatim from the story's acceptance criteria.
    if file_count < rule.minimum:
        message = (
            f"Only found {file_count} speech files for {fmt}. "
            f"Minimum is {rule.minimum} ({rule.min_note}). Proceed anyway?"
        )
    else:
        message = (
            f"Found {file_count} speech files for {fmt}. "
            f"Maximum expected is {rule.maximum} ({rule.max_note}). "
            f"Proceed anyway?"
        )

    if not (confirm or _default_confirm)(message):
        raise IngestAborted(message)


def _default_chooser(items: List[Path]) -> int:
    """
    Interactive picker for a non-empty inbox with more than one round.

    Returns a 0-based index, or -1 meaning "all of them". Imported lazily so
    that ingest.py stays usable without click (tests inject their own chooser).
    """
    import click

    click.echo(f"\nMultiple rounds in the inbox:", err=True)
    for index, item in enumerate(items, 1):
        kind = "folder" if item.is_dir() else "file"
        click.echo(f"  {index}. {item.name} ({kind})", err=True)
    click.echo(f"  {len(items) + 1}. Judge all in sequence", err=True)

    choice = click.prompt(
        "Pick one", type=click.IntRange(1, len(items) + 1), err=True
    )
    return -1 if choice == len(items) + 1 else choice - 1


def _build_round_input(
    path: Path,
    debate_format: str,
    confirm: Optional[Callable[[str], bool]] = None,
) -> RoundInput:
    """Turn a chosen file or folder into a RoundInput, validating as we go."""
    if path.is_dir():
        files = transcript_files_in(path)
        if not files:
            raise IngestError(
                f"No speech files found in {path}. "
                f"v0.1 accepts .txt and .rtf files, or folders of them."
            )
        # Count validation runs before per-file reads: if the folder is
        # obviously not a round, say so before spending time on its contents.
        validate_file_count(debate_format, len(files), confirm=confirm)
        for file in files:
            validate_transcript_file(file)
        # Story 2.3: reorder into canonical debate order where the filenames
        # allow it. Alphanumeric order would put an LD 1AR before the 1NC.
        files = order_speech_files(files, normalize_debate_format(debate_format))
        return RoundInput(
            path=path,
            files=files,
            is_folder=True,
            debate_format=normalize_debate_format(debate_format),
            metadata_file=metadata_file_in(path),
        )

    # Mode A is a single file by definition, so file-count rules don't apply.
    validate_transcript_file(path)
    return RoundInput(
        path=path,
        files=[path],
        is_folder=False,
        debate_format=normalize_debate_format(debate_format),
        metadata_file=metadata_file_in(path.parent, stem=path.stem),
    )


def load_round_input(
    path_or_type: str,
    debate_format: str = "LD",
    select_all: bool = False,
    chooser: Optional[Callable[[List[Path]], int]] = None,
    confirm: Optional[Callable[[str], bool]] = None,
) -> List[RoundInput]:
    """
    Resolve the CLI argument into one or more rounds to judge (Story 1.1).

    `path_or_type` is either a debate type (auto-pick from that inbox) or an
    explicit path to a .txt file or a folder of them. Returns a list so that
    `--all` can judge an inbox in sequence; ordinary runs get one element.
    """
    argument = path_or_type.strip()

    # Mode: debate type -> auto-pick from the inbox.
    if is_debate_format(argument):
        resolved_format = normalize_debate_format(argument)
        inbox = inbox_for(resolved_format)
        items = list_inbox_items(resolved_format)

        if not items:
            raise IngestError(
                f"No rounds found in {inbox}. "
                f"Drop transcript files there and try again."
            )

        if len(items) == 1:
            return [_build_round_input(items[0], resolved_format, confirm)]

        if select_all:
            return [_build_round_input(item, resolved_format, confirm) for item in items]

        index = (chooser or _default_chooser)(items)
        if index == -1:
            return [_build_round_input(item, resolved_format, confirm) for item in items]
        return [_build_round_input(items[index], resolved_format, confirm)]

    # Mode: explicit path.
    path = Path(argument).expanduser()
    if not path.exists():
        raise IngestError(
            f"File not found: {path}. Provide a valid .txt file, a folder of "
            f"speech files, or a debate type ({'/'.join(DEBATE_TYPES)})."
        )

    return [_build_round_input(path, debate_format, confirm)]
