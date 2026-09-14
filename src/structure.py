"""
Speech structure: canonical sequences and filename-based labeling (Story 2.3).

When speech files are already named recognizably (`1AC.txt`, `01_1AC.txt`,
`cross_1.txt`), their labels can be read straight off the filename — no model
call needed, which saves both a round trip and its cost.

Labeling also fixes ordering. Alphanumeric sorting of bare LD speech names
yields `1AC, 1AR, 1NC, 2AR, 2NR, CX1, CX2`, placing the 1AR before the 1NC it
answers. Files are therefore reordered into the debate's canonical sequence
(User Stories Story 1.2 "Speech ordering rule", Story 2.3 ordering authority).

Model-based detection for unlabeled files is Story 2.1.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

AFF = "Aff"
NEG = "Neg"
BOTH = "Both"

SOURCE_FILENAME = "filename"
SOURCE_MODEL = "model"
SOURCE_UNLABELED = "unlabeled"
SOURCE_EDITED = "edited"


@dataclass(frozen=True)
class SpeechSlot:
    """One position in a debate format's fixed sequence."""

    label: str
    speaker: str
    position: int
    description: str


# Canonical LD sequence — the ordering authority for Story 2.3.
LD_SEQUENCE: Tuple[SpeechSlot, ...] = (
    SpeechSlot("1AC", AFF, 1, "Affirmative constructive"),
    SpeechSlot("CX1", BOTH, 2, "Neg questions Aff"),
    SpeechSlot("1NC", NEG, 3, "Negative constructive"),
    SpeechSlot("CX2", BOTH, 4, "Aff questions Neg"),
    SpeechSlot("1AR", AFF, 5, "First affirmative rebuttal"),
    SpeechSlot("2NR", NEG, 6, "Second negative rebuttal"),
    SpeechSlot("2AR", AFF, 7, "Second affirmative rebuttal"),
)

# v0.1 implements LD only; other formats arrive in v0.5.
SEQUENCES: Dict[str, Tuple[SpeechSlot, ...]] = {"LD": LD_SEQUENCE}


def sequence_for(debate_format: str) -> Tuple[SpeechSlot, ...]:
    """The canonical speech sequence for a format, or empty if unsupported."""
    return SEQUENCES.get(debate_format, ())


def slot_for(label: str, debate_format: str = "LD") -> Optional[SpeechSlot]:
    for slot in sequence_for(debate_format):
        if slot.label == label:
            return slot
    return None


def expected_labels(debate_format: str = "LD") -> List[str]:
    return [slot.label for slot in sequence_for(debate_format)]


# --- filename -> label -------------------------------------------------

# LD has exactly one of each speech, so a bare "AC" is unambiguous.
_BARE_ALIASES = {"ac": "1AC", "nc": "1NC", "ar": "1AR", "nr": "2NR"}

# Spelled-out forms. Rebuttals are deliberately absent: "aff_rebuttal" could
# mean 1AR or 2AR, and guessing wrong silently mis-orders the round. Ambiguous
# names fall through to model detection instead.
_WORD_FORMS = (
    (re.compile(r"^(?:aff|affirmative|a)constructive$"), "1AC"),
    (re.compile(r"^(?:neg|negative|n)constructive$"), "1NC"),
    (re.compile(r"^constructive(?:aff|affirmative)$"), "1AC"),
    (re.compile(r"^constructive(?:neg|negative)$"), "1NC"),
)

_SEPARATORS = re.compile(r"[\s_\-.]+")
_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _tokens(stem: str) -> List[str]:
    """
    Split a filename stem into tokens, dropping a leading numeric index.

    `01_1AC` -> ["1AC"]: the `01` is an ordering prefix, not part of the label.
    `1AC` -> ["1AC"]: not a pure-digit token, so nothing is dropped.
    """
    parts = [part for part in _SEPARATORS.split(stem) if part]
    if len(parts) > 1 and parts[0].isdigit():
        parts = parts[1:]
    return parts


def _normalize(text: str) -> str:
    return _NON_ALNUM.sub("", text.lower())


def _match_label(normalized: str, debate_format: str) -> Optional[str]:
    """Map one normalized token (or whole stem) to a canonical label."""
    if not normalized:
        return None

    valid = set(expected_labels(debate_format))

    # Cross-examination, in its many spellings.
    cross = re.match(r"^(?:cx|crossex\w*|cross)(\d*)$", normalized)
    if cross:
        number = cross.group(1) or "1"  # a bare "CX" means the first one
        label = f"CX{number}"
        return label if label in valid else None

    cross_suffix = re.match(r"^(\d+)(?:cx|crossex\w*|cross)$", normalized)
    if cross_suffix:
        label = f"CX{cross_suffix.group(1)}"
        return label if label in valid else None

    # Numbered speech labels: 1ac, 1nc, 1ar, 2nr, 2ar.
    numbered = re.match(r"^(\d)(ac|nc|ar|nr)$", normalized)
    if numbered:
        label = f"{numbered.group(1)}{numbered.group(2).upper()}"
        return label if label in valid else None

    if normalized in _BARE_ALIASES:
        label = _BARE_ALIASES[normalized]
        return label if label in valid else None

    for pattern, label in _WORD_FORMS:
        if pattern.match(normalized) and label in valid:
            return label

    return None


def label_from_filename(path: Path, debate_format: str = "LD") -> Optional[str]:
    """
    Read a speech label off a filename, or return None if it isn't recognizable.

    Tries the whole stem first, then individual tokens, so `1AC_final.txt` still
    resolves while `speech_01.txt` correctly does not.
    """
    tokens = _tokens(path.stem)

    whole = _match_label(_normalize("".join(tokens)), debate_format)
    if whole:
        return whole

    matches = {
        label
        for token in tokens
        if (label := _match_label(_normalize(token), debate_format))
    }
    # Exactly one candidate is a confident read; two competing labels are not.
    return matches.pop() if len(matches) == 1 else None


# --- labeling a whole folder -------------------------------------------


@dataclass
class LabeledSpeech:
    """One input file with whatever we know about its place in the round."""

    path: Path
    label: Optional[str] = None
    speaker: Optional[str] = None
    position: Optional[int] = None
    source: str = SOURCE_UNLABELED

    @property
    def is_labeled(self) -> bool:
        return self.label is not None


@dataclass
class LabelingResult:
    """Outcome of filename-based labeling for a folder of speech files."""

    speeches: List[LabeledSpeech] = field(default_factory=list)
    duplicates: List[str] = field(default_factory=list)

    @property
    def all_labeled(self) -> bool:
        return bool(self.speeches) and all(s.is_labeled for s in self.speeches)

    @property
    def needs_model(self) -> bool:
        """
        Whether a structure-detection model call is still required (Story 2.3).

        Confidently labeled folders skip the call. Anything unlabeled — or any
        label claimed by two files — falls through to the model rather than
        guessing.
        """
        return not self.all_labeled or bool(self.duplicates)

    @property
    def labeled_count(self) -> int:
        return sum(1 for s in self.speeches if s.is_labeled)

    @property
    def missing_labels(self) -> List[str]:
        """Canonical labels no file claimed."""
        claimed = {s.label for s in self.speeches if s.label}
        return [label for label in self._expected if label not in claimed]

    _expected: List[str] = field(default_factory=list, repr=False)


def label_files(
    files: Sequence[Path], debate_format: str = "LD"
) -> LabelingResult:
    """
    Label a folder's files from their names and order them canonically.

    Files that can be labeled are sorted into the debate's fixed sequence.
    Unlabeled files keep their incoming relative order and follow the labeled
    ones, awaiting model detection (Story 2.1).
    """
    speeches: List[LabeledSpeech] = []
    seen: Dict[str, int] = {}
    duplicates: List[str] = []

    for path in files:
        label = label_from_filename(path, debate_format)
        if label is not None:
            seen[label] = seen.get(label, 0) + 1
            if seen[label] == 2:
                # Two files claiming one speech: don't pick a winner.
                duplicates.append(label)
        slot = slot_for(label, debate_format) if label else None
        speeches.append(
            LabeledSpeech(
                path=path,
                label=label,
                speaker=slot.speaker if slot else None,
                position=slot.position if slot else None,
                source=SOURCE_FILENAME if label else SOURCE_UNLABELED,
            )
        )

    result = LabelingResult(
        speeches=_ordered(speeches, duplicates),
        duplicates=sorted(duplicates),
    )
    result._expected = expected_labels(debate_format)
    return result


def _ordered(
    speeches: List[LabeledSpeech], duplicates: List[str]
) -> List[LabeledSpeech]:
    """
    Sort labeled speeches into canonical order; leave the rest where they are.

    With duplicate labels, ordering is left untouched — the folder is going to
    the model anyway, and a half-applied reordering would only obscure that.
    """
    if duplicates:
        return speeches

    labeled = sorted(
        (s for s in speeches if s.position is not None), key=lambda s: s.position
    )
    unlabeled = [s for s in speeches if s.position is None]
    return labeled + unlabeled


def order_speech_files(
    files: Sequence[Path], debate_format: str = "LD"
) -> List[Path]:
    """
    Reorder input files into canonical speech order where names allow it.

    Called at load time so every downstream step — preview, judging, archiving —
    sees the round in the sequence it was actually debated in.
    """
    return [speech.path for speech in label_files(files, debate_format).speeches]
