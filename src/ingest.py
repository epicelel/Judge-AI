"""Round input loading for JudgeAI v0.1 (LD only)."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .documents import DocumentError, is_transcript_file, read_transcript_text
from .structure import order_speech_files

JUDGEAI_ROOT = Path.home() / "Desktop" / "JudgeAI"
INBOX_ROOT = JUDGEAI_ROOT / "New_Rounds"
ARCHIVE_ROOT = JUDGEAI_ROOT / "Past_Rounds"

# The structure/detection pipeline in v0.1 only implements Lincoln-Douglas.
DEBATE_TYPES = ("LD", "PF", "Worlds", "Congress", "Parli")
METADATA_SUFFIXES = (".yaml", ".yml")
MIN_TRANSCRIPT_CHARS = 200


@dataclass(frozen=True)
class FileCountRule:
    minimum: int
    maximum: int
    max_note: str
    min_note: str = "all debate speeches"


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
    """The user declined a confirmation prompt."""


@dataclass
class RoundInput:
    path: Path
    files: List[Path]
    is_folder: bool
    debate_format: str = "LD"
    metadata_file: Optional[Path] = field(default=None)

    @property
    def name(self) -> str:
        return self.path.name

    def read_text(self) -> str:
        return "\n\n".join(read_transcript_text(file) for file in self.files)


def normalize_debate_format(value: str) -> str:
    value = value.strip()
    for known in DEBATE_TYPES:
        if value.lower() == known.lower():
            return known
    return value


def is_debate_format(value: str) -> bool:
    return normalize_debate_format(value) in DEBATE_TYPES


def inbox_for(debate_format: str) -> Path:
    return INBOX_ROOT / normalize_debate_format(debate_format)


def _natural_key(path: Path):
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r"(\d+)", path.name)
    ]


def _is_hidden(path: Path) -> bool:
    return path.name.startswith(".")


def transcript_files_in(folder: Path) -> List[Path]:
    return sorted(
        (
            path
            for path in folder.iterdir()
            if path.is_file() and is_transcript_file(path) and not _is_hidden(path)
        ),
        key=_natural_key,
    )


def metadata_file_in(folder: Path, stem: Optional[str] = None) -> Optional[Path]:
    candidates = sorted(
        (
            path
            for path in folder.iterdir()
            if path.is_file()
            and path.suffix.lower() in METADATA_SUFFIXES
            and not _is_hidden(path)
        ),
        key=_natural_key,
    )
    if stem:
        for candidate in candidates:
            if candidate.stem.lower() == stem.lower():
                return candidate
    return candidates[0] if candidates else None


def list_inbox_items(debate_format: str) -> List[Path]:
    inbox = inbox_for(debate_format)
    if not inbox.exists():
        return []
    items = [
        path
        for path in inbox.iterdir()
        if not _is_hidden(path) and (path.is_dir() or is_transcript_file(path))
    ]
    return sorted(items, key=lambda path: (path.is_file(), _natural_key(path)))


def validate_transcript_file(path: Path) -> None:
    if not is_transcript_file(path):
        raise IngestError(
            f"Unsupported file type: {path.suffix}. v0.1 accepts .txt and .rtf files, or folders of them."
        )
    try:
        content = read_transcript_text(path)
    except DocumentError as exc:
        raise IngestError(str(exc)) from exc
    if len(content.strip()) < MIN_TRANSCRIPT_CHARS:
        raise IngestError(
            f"Transcript too short (<{MIN_TRANSCRIPT_CHARS} chars). Not a real round."
        )


def _default_confirm(message: str) -> bool:
    import click

    try:
        return click.confirm(message, default=False, err=True)
    except (click.Abort, EOFError, OSError) as exc:
        raise IngestError(
            f"{message}\nCannot prompt: no input available. "
            f"Re-run with --yes to accept prompts automatically."
        ) from exc


def validate_file_count(
    debate_format: str,
    file_count: int,
    confirm: Optional[Callable[[str], bool]] = None,
) -> None:
    fmt = normalize_debate_format(debate_format)
    rule = FILE_COUNT_RULES.get(fmt)
    if rule is None or rule.minimum <= file_count <= rule.maximum:
        return

    if file_count < rule.minimum:
        message = (
            f"Only found {file_count} speech files for {fmt}. "
            f"Minimum is {rule.minimum} ({rule.min_note}). Proceed anyway?"
        )
    else:
        message = (
            f"Found {file_count} speech files for {fmt}. "
            f"Maximum expected is {rule.maximum} ({rule.max_note}). Proceed anyway?"
        )

    if not (confirm or _default_confirm)(message):
        raise IngestAborted(message)


def _default_chooser(items: List[Path]) -> int:
    import click

    click.echo("\nMultiple rounds in the inbox:", err=True)
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
    debate_format = normalize_debate_format(debate_format)

    if path.is_dir():
        files = transcript_files_in(path)
        if not files:
            raise IngestError(
                f"No speech files found in {path}. v0.1 accepts .txt and .rtf files, or folders of them."
            )
        validate_file_count(debate_format, len(files), confirm=confirm)
        for file in files:
            validate_transcript_file(file)
        files = order_speech_files(files, debate_format)
        return RoundInput(
            path=path,
            files=files,
            is_folder=True,
            debate_format=debate_format,
            metadata_file=metadata_file_in(path),
        )

    validate_transcript_file(path)
    return RoundInput(
        path=path,
        files=[path],
        is_folder=False,
        debate_format=debate_format,
        metadata_file=metadata_file_in(path.parent, stem=path.stem),
    )


def load_round_input(
    path_or_type: str,
    debate_format: str = "LD",
    select_all: bool = False,
    chooser: Optional[Callable[[List[Path]], int]] = None,
    confirm: Optional[Callable[[str], bool]] = None,
) -> List[RoundInput]:
    argument = path_or_type.strip()
    debate_format = normalize_debate_format(debate_format)

    if is_debate_format(argument):
        resolved_format = normalize_debate_format(argument)
        inbox = inbox_for(resolved_format)
        items = list_inbox_items(resolved_format)
        if not items:
            raise IngestError(
                f"No rounds found in {inbox}. Drop transcript files there and try again."
            )
        if len(items) == 1:
            return [_build_round_input(items[0], resolved_format, confirm)]
        if select_all:
            return [_build_round_input(item, resolved_format, confirm) for item in items]
        index = (chooser or _default_chooser)(items)
        if index == -1:
            return [_build_round_input(item, resolved_format, confirm) for item in items]
        return [_build_round_input(items[index], resolved_format, confirm)]

    # Path.expanduser() on Windows ignores a monkeypatched HOME and prefers
    # USERPROFILE. Honor HOME explicitly so documented ~/ paths behave the same
    # on Windows, macOS, and Linux.
    if argument == "~" or argument.startswith(("~/", "~\\")):
        home = os.environ.get("HOME")
        if home:
            remainder = argument[2:] if len(argument) > 1 else ""
            path = Path(home) / remainder
        else:
            path = Path(argument).expanduser()
    else:
        path = Path(argument).expanduser()

    if not path.exists():
        # Preserve the user's spelling/slashes in the error instead of rendering
        # a POSIX path with Windows backslashes.
        raise IngestError(
            f"File not found: {argument}. Provide a valid .txt file, a folder of "
            f"speech files, or a debate type ({'/'.join(DEBATE_TYPES)})."
        )
    return [_build_round_input(path, debate_format, confirm)]
