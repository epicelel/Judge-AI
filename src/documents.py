"""
Reading transcript text out of the formats it actually arrives in.

`.txt` is read directly. `.rtf` is TextEdit's default save format on macOS and is
what transcripts are usually saved as, so it is converted on read — in memory
only. The original file is never modified, and it is the original that gets
archived (Story 1.1, revised 2026-08-14).
"""

import re
import shutil
import subprocess
from pathlib import Path

TXT_SUFFIX = ".txt"
RTF_SUFFIX = ".rtf"
TRANSCRIPT_SUFFIXES = (TXT_SUFFIX, RTF_SUFFIX)

# macOS ships this; it handles RTF far more reliably than a regex ever will.
TEXTUTIL = "/usr/bin/textutil"
CONVERSION_TIMEOUT_SECONDS = 30


class DocumentError(Exception):
    """A transcript file could not be read or converted."""


def is_transcript_file(path: Path) -> bool:
    return path.suffix.lower() in TRANSCRIPT_SUFFIXES


def read_transcript_text(path: Path) -> str:
    """
    Return a file's plain text, converting RTF if needed.

    Never returns RTF markup: a conversion failure raises, because feeding
    `\\rtf1\\ansi...` to the model would produce a confidently wrong ballot with
    nothing in the output explaining why.
    """
    path = Path(path)
    if path.suffix.lower() == RTF_SUFFIX:
        return _rtf_to_text(path)
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DocumentError(f"Could not read {path.name}: {exc}") from exc


def _rtf_to_text(path: Path) -> str:
    """Convert RTF via textutil, falling back to a markup stripper."""
    if Path(TEXTUTIL).exists():
        try:
            completed = subprocess.run(
                [TEXTUTIL, "-convert", "txt", "-stdout", str(path)],
                capture_output=True,
                timeout=CONVERSION_TIMEOUT_SECONDS,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DocumentError(
                f"Could not convert {path.name} from RTF: {exc}. "
                f"Re-save it as plain text and try again."
            ) from exc
        text = completed.stdout.decode("utf-8", errors="replace")
        if text.strip():
            return text
        # An empty result means textutil didn't recognize the file; try the
        # stripper rather than silently treating the round as empty.

    return _strip_rtf(_read_bytes(path))


def _read_bytes(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError as exc:
        raise DocumentError(f"Could not read {path.name}: {exc}") from exc


# Minimal RTF stripper, used only when textutil is unavailable or unhelpful.
_RTF_ESCAPES = {r"\\par": "\n", r"\\line": "\n", r"\\tab": "\t"}


def _strip_rtf(raw: str) -> str:
    if "\\rtf" not in raw[:512]:
        raise DocumentError(
            "File has an .rtf extension but does not look like RTF. "
            "Re-save it as plain text and try again."
        )

    text = raw
    for pattern, replacement in _RTF_ESCAPES.items():
        text = re.sub(pattern + r"\b", replacement, text)
    text = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r"\{\\\*?\\[^{}]*\}", "", text)   # drop control groups
    text = re.sub(r"\\[a-zA-Z]+-?\d*\s?", "", text)  # drop control words
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\n{3,}", "\n\n", text)

    if not text.strip():
        raise DocumentError(
            "RTF conversion produced no text. Re-save the file as plain text."
        )
    return text
