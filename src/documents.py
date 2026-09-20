"""
Reading transcript text out of the formats it actually arrives in.

`.txt` is read directly. `.rtf` is TextEdit's default save format on macOS and is
what transcripts are usually saved as, so it is converted on read — in memory
only. The original file is never modified, and it is the original that gets
archived.
"""

import subprocess
from pathlib import Path

TXT_SUFFIX = ".txt"
RTF_SUFFIX = ".rtf"
TRANSCRIPT_SUFFIXES = (TXT_SUFFIX, RTF_SUFFIX)
TEXTUTIL = "/usr/bin/textutil"
CONVERSION_TIMEOUT_SECONDS = 30


class DocumentError(Exception):
    """A transcript file could not be read or converted."""


def is_transcript_file(path: Path) -> bool:
    return Path(path).suffix.lower() in TRANSCRIPT_SUFFIXES


def read_transcript_text(path: Path) -> str:
    """Return plain transcript text, converting RTF in memory when needed."""
    path = Path(path)
    if path.suffix.lower() == RTF_SUFFIX:
        return _rtf_to_text(path)
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DocumentError(f"Could not read {path.name}: {exc}") from exc


def _rtf_to_text(path: Path) -> str:
    """Convert RTF via macOS textutil, with a cross-platform Python fallback."""
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
    return _strip_rtf(_read_bytes(path))


def _read_bytes(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError as exc:
        raise DocumentError(f"Could not read {path.name}: {exc}") from exc


# RTF destinations contain metadata rather than visible transcript text. The old
# regex fallback stripped control words but accidentally left values such as the
# font name "Helvetica" behind on Windows, which inflated word counts.
_DESTINATIONS = {
    "fonttbl",
    "colortbl",
    "stylesheet",
    "info",
    "pict",
    "object",
    "filetbl",
    "listtable",
    "listoverridetable",
    "generator",
    "header",
    "headerl",
    "headerr",
    "headerf",
    "footer",
    "footerl",
    "footerr",
    "footerf",
}


def _strip_rtf(raw: str) -> str:
    """
    Minimal cross-platform RTF-to-text parser.

    It intentionally ignores formatting and metadata destinations while keeping
    visible text, paragraph/line breaks, tabs, escaped hex characters, Unicode
    escapes, and escaped literal braces/backslashes.
    """
    if "\\rtf" not in raw[:512]:
        raise DocumentError(
            "File has an .rtf extension but does not look like RTF. "
            "Re-save it as plain text and try again."
        )

    # State per group: (skip_destination, unicode_fallback_char_count)
    stack = []
    skip_destination = False
    uc_skip = 1
    skip_plain_chars = 0
    output = []
    i = 0
    n = len(raw)

    while i < n:
        ch = raw[i]

        if ch == "{":
            stack.append((skip_destination, uc_skip))
            i += 1
            continue

        if ch == "}":
            if stack:
                skip_destination, uc_skip = stack.pop()
            i += 1
            continue

        if ch != "\\":
            if skip_plain_chars > 0:
                skip_plain_chars -= 1
            elif not skip_destination:
                output.append(ch)
            i += 1
            continue

        # Backslash begins either an escaped literal/symbol or a control word.
        i += 1
        if i >= n:
            break

        symbol = raw[i]

        if symbol in "\\{}":
            if not skip_destination:
                output.append(symbol)
            i += 1
            continue

        if symbol == "'":
            if i + 2 < n:
                hex_value = raw[i + 1 : i + 3]
                try:
                    decoded = bytes([int(hex_value, 16)]).decode("cp1252")
                except (ValueError, UnicodeDecodeError):
                    decoded = ""
                if not skip_destination:
                    output.append(decoded)
                i += 3
            else:
                i += 1
            continue

        if symbol == "*":
            # Ignorable destination marker; the following control word names it.
            skip_destination = True
            i += 1
            continue

        if not symbol.isalpha():
            # Control symbols such as \~ (non-breaking space), \- and \_.
            if not skip_destination:
                if symbol == "~":
                    output.append(" ")
                elif symbol in ("-", "_"):
                    output.append("-")
            i += 1
            continue

        start = i
        while i < n and raw[i].isalpha():
            i += 1
        word = raw[start:i]

        sign = 1
        if i < n and raw[i] == "-":
            sign = -1
            i += 1
        num_start = i
        while i < n and raw[i].isdigit():
            i += 1
        number = None
        if i > num_start:
            number = sign * int(raw[num_start:i])

        # A space delimiting a control word is syntax, not output.
        if i < n and raw[i] == " ":
            i += 1

        if word in _DESTINATIONS:
            skip_destination = True
            continue

        if word == "uc" and number is not None:
            uc_skip = max(0, number)
            continue

        if skip_destination:
            continue

        if word in ("par", "line"):
            output.append("\n")
        elif word == "tab":
            output.append("\t")
        elif word == "u" and number is not None:
            codepoint = number if number >= 0 else number + 65536
            try:
                output.append(chr(codepoint))
            except ValueError:
                output.append("�")
            skip_plain_chars = uc_skip
        # All other control words are formatting and are intentionally ignored.

    text = "".join(output)
    # Normalize only excessive blank lines; preserve normal paragraph boundaries.
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    if not text.strip():
        raise DocumentError(
            "RTF conversion produced no text. Re-save the file as plain text."
        )
    return text
