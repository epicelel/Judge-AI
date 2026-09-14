"""
Assembling a structured transcript from labeled speeches.

This is the text handed to every model call — structure detection, each judge
persona, and the cross-paradigm diff — and it is what gets written to
`structured_transcript.md` for reference (Story 2.1, Story 5.1).

Speech boundaries are marked explicitly so a persona can refer to "in the 1AR,
AFF drops..." rather than guessing where one speech ended.
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Sequence

from .documents import read_transcript_text
from .structure import LabeledSpeech

UNKNOWN_SPEAKER = "Unknown"


def word_count(text: str) -> int:
    return len(text.split())


def read_speech_text(source) -> str:
    """
    Read one speech's text, whatever is holding it.

    A speech may be backed by a real file (possibly .rtf), a segment split out of
    a detected transcript, or a block that came back from the editor. Routing all
    three through here is what keeps RTF markup from reaching the model.
    """
    if isinstance(source, Path):
        return read_transcript_text(source)
    return source.read_text()


def speech_header(speech: LabeledSpeech, index: int, words: int) -> str:
    """
    Delimiter line introducing one speech.

    Unlabeled segments fall back to a positional name so the model still sees a
    boundary; Story 2.1's detection pass replaces these with real labels.
    """
    label = speech.label or f"Speech {index}"
    speaker = speech.speaker or UNKNOWN_SPEAKER
    return f"=== {label} ({speaker}, {words:,} words) ==="


def format_round_header(
    debate_format: str = "LD",
    resolution: Optional[str] = None,
    aff: Optional[str] = None,
    neg: Optional[str] = None,
) -> str:
    """
    Context block naming the format, resolution, and speakers.

    Speaker names are what let ballots say "Eliana's dignity framing" instead of
    "the affirmative's second contention" (MVP §4.6).
    """
    lines = ["ROUND", f"Format: {debate_format}"]
    if resolution:
        lines.append(f'Resolution: "{resolution}"')
    else:
        lines.append("Resolution: (not provided)")
    lines.append(f"Aff: {aff or 'Aff'} | Neg: {neg or 'Neg'}")
    return "\n".join(lines)


def format_structured_transcript(
    speeches: Sequence[LabeledSpeech],
    debate_format: str = "LD",
    resolution: Optional[str] = None,
    aff: Optional[str] = None,
    neg: Optional[str] = None,
    include_header: bool = True,
) -> str:
    """
    Render labeled speeches into one delimited transcript, in order.

    Speech text comes from each file on disk; nothing is re-read later, so the
    assembled string is the single source of truth for what the model saw.
    """
    blocks = []
    if include_header:
        blocks.append(
            format_round_header(debate_format, resolution, aff, neg)
        )

    for index, speech in enumerate(speeches, 1):
        content = read_speech_text(speech.path).strip()
        blocks.append(
            f"{speech_header(speech, index, word_count(content))}\n\n{content}"
        )

    return "\n\n".join(blocks) + "\n"


def summarize_speeches(speeches: Sequence[LabeledSpeech]) -> list:
    """
    Per-speech summary rows for the confirmation preview (Story 2.2).

    Returns dicts rather than a formatted string so the CLI owns presentation.
    """
    rows = []
    for index, speech in enumerate(speeches, 1):
        content = read_speech_text(speech.path)
        rows.append(
            {
                "index": index,
                "label": speech.label or f"Speech {index}",
                "speaker": speech.speaker or UNKNOWN_SPEAKER,
                "words": word_count(content),
                "source": speech.source,
                "file": speech.path.name,
            }
        )
    return rows


# --- Story 2.2: editing a structured transcript by hand -----------------

EDITOR_ENV_VARS = ("JUDGEAI_EDITOR", "VISUAL", "EDITOR")
DEFAULT_EDITOR = "nano"

SPEECH_HEADER_PATTERN = re.compile(
    r"^===\s*(?P<label>[^(]+?)\s*(?:\((?P<speaker>[^,)]+)(?:,[^)]*)?\))?\s*===\s*$"
)


def resolve_editor() -> str:
    """
    Which editor to open for `edit` (Story 2.2).

    JUDGEAI_EDITOR wins so a debug editor can be set without disturbing the
    user's normal VISUAL/EDITOR.
    """
    for name in EDITOR_ENV_VARS:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return DEFAULT_EDITOR


def parse_structured_transcript(text: str) -> List["LabeledSpeech"]:
    """
    Read a structured transcript back into speeches.

    Needed because `edit` lets the user move boundaries by hand, and their edits
    have to become the speeches that get judged. Word counts in the headers are
    recomputed from the body rather than trusted.
    """
    from .structure import SOURCE_EDITED, LabeledSpeech, slot_for

    speeches: List[LabeledSpeech] = []
    label: Optional[str] = None
    speaker: Optional[str] = None
    body: List[str] = []

    def flush() -> None:
        if label is None:
            return
        slot = slot_for(label)
        speeches.append(
            LabeledSpeech(
                path=EditedSegment(label, "\n".join(body).strip()),
                label=label,
                speaker=speaker or (slot.speaker if slot else None),
                position=slot.position if slot else None,
                source=SOURCE_EDITED,
            )
        )

    for line in text.splitlines():
        match = SPEECH_HEADER_PATTERN.match(line)
        if match:
            flush()
            label = match.group("label").strip()
            speaker = (match.group("speaker") or "").strip() or None
            body = []
        elif label is not None:
            body.append(line)
        # Lines before the first header are the ROUND block; ignored on re-read.

    flush()
    return [s for s in speeches if s.path.read_text().strip()]


class EditedSegment:
    """Path-like holder for a speech that came back from the editor."""

    def __init__(self, label: str, content: str):
        self._label = label
        self._content = content

    @property
    def name(self) -> str:
        return f"{self._label} (edited)"

    @property
    def stem(self) -> str:
        return self._label

    def read_text(self, *_args, **_kwargs) -> str:
        return self._content

    def __fspath__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<edited {self._label}: {len(self._content)} chars>"
