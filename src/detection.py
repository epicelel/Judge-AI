"""
Model-based structure detection (Story 2.1) and resolution extraction (2.4).

The model returns only *markers* — the first few words of each speech — and the
transcript is split locally. Returning the segmented text instead would cost as
many output tokens as input, and would let the model silently alter the
transcript it is meant to be indexing.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .prompts import load_prompt
from .structure import (
    SOURCE_MODEL,
    LabeledSpeech,
    expected_labels,
    slot_for,
)

DETECTION_PROMPT = "shared/structure_detection"
DETECTION_MAX_TOKENS = 2048
# Structural indexing, not creative work: keep it deterministic.
DETECTION_TEMPERATURE = 0.0
# Shortest prefix worth attempting when a full marker will not match.
MIN_MARKER_WORDS = 4


class DetectionError(Exception):
    """Detection failed in a way the user can act on."""


@dataclass
class DetectedSpeech:
    """One speech the model located, before the transcript is split."""

    label: str
    speaker: Optional[str]
    start_marker: str
    start_index: Optional[int] = None


@dataclass
class DetectionResult:
    speeches: List[DetectedSpeech] = field(default_factory=list)
    resolution_text: Optional[str] = None
    resolution_quote: Optional[str] = None
    resolution_confidence: str = "low"
    notes: str = ""
    unmatched_markers: List[str] = field(default_factory=list)
    # Characters before the first located speech. Usually a file header or a
    # leading timestamp, so discarding it is desirable — but it is reported
    # rather than dropped silently, in case real content preceded the 1AC.
    preamble_chars: int = 0

    @property
    def labels(self) -> List[str]:
        return [s.label for s in self.speeches]


def extract_json(text: str) -> Dict[str, Any]:
    """
    Pull a JSON object out of a model response.

    Models wrap JSON in prose or a ```json fence often enough that retrying the
    call is wasteful when the payload is right there.
    """
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise DetectionError(
        "Structure detection did not return usable JSON. "
        "Re-run with --verbose to see the raw response."
    )


def _normalize(text: str) -> str:
    """Collapse whitespace and drop punctuation for fuzzy marker matching."""
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", text.lower())).strip()


def locate_marker(transcript: str, marker: str, search_from: int = 0) -> Optional[int]:
    """
    Find where a marker begins in the transcript.

    Three passes, loosening each time:
      1. exact substring match
      2. normalized match, ignoring whitespace, punctuation, and bracketed
         timestamps like `[00:09]`
      3. normalized match on a shortening prefix of the marker

    Passes 2 and 3 exist because of a real failure on a 36KB Otter transcript:
    the model quoted a marker that spanned an inline `[00:09]` timestamp, so the
    literal text never appeared and the entire 1AC was dropped as preamble.
    """
    if not marker.strip():
        return None

    index = transcript.find(marker, search_from)
    if index != -1:
        return index

    haystack, raw_positions = _normalized_index(transcript)

    def find_normalized(needle: str) -> Optional[int]:
        if not needle:
            return None
        cursor = 0
        while True:
            found = haystack.find(needle, cursor)
            if found == -1:
                return None
            raw = raw_positions[found]
            if raw >= search_from:
                return raw
            cursor = found + 1

    located = find_normalized(_normalize(marker))
    if located is not None:
        return located

    # Progressively shorter prefixes: the start of a marker is far likelier to
    # be verbatim than its tail.
    words = _normalize(marker).split()
    for length in range(len(words) - 1, MIN_MARKER_WORDS - 1, -1):
        located = find_normalized(" ".join(words[:length]))
        if located is not None:
            return located
    return None


def _normalized_index(transcript: str) -> Tuple[str, List[int]]:
    """
    Build a comparison string plus a map back to raw offsets.

    Bracketed spans are skipped entirely: transcription timestamps sit inline
    between words a model is likely to quote as one continuous phrase.
    """
    raw_positions: List[int] = []
    chars: List[str] = []
    previous_space = False
    in_bracket = False

    for offset, char in enumerate(transcript):
        if char == "[":
            in_bracket = True
            continue
        if in_bracket:
            if char == "]":
                in_bracket = False
            continue

        lowered = char.lower()
        if lowered.isalnum():
            chars.append(lowered)
            raw_positions.append(offset)
            previous_space = False
        elif char.isspace() and not previous_space:
            chars.append(" ")
            raw_positions.append(offset)
            previous_space = True

    return "".join(chars), raw_positions


def split_transcript(
    transcript: str, speeches: List[DetectedSpeech]
) -> Tuple[List[Tuple[DetectedSpeech, str]], List[str]]:
    """
    Cut the transcript at each located marker.

    Markers are located left to right so a later speech can't match text earlier
    in the round. Anything that can't be found is reported rather than dropped
    silently.
    """
    located: List[DetectedSpeech] = []
    unmatched: List[str] = []
    cursor = 0
    for speech in speeches:
        index = locate_marker(transcript, speech.start_marker, cursor)
        if index is None:
            unmatched.append(speech.label)
            continue
        speech.start_index = index
        cursor = index + 1
        located.append(speech)

    segments: List[Tuple[DetectedSpeech, str]] = []
    for position, speech in enumerate(located):
        end = (
            located[position + 1].start_index
            if position + 1 < len(located)
            else len(transcript)
        )
        segments.append((speech, transcript[speech.start_index : end].strip()))
    return segments, unmatched


def parse_detection(payload: Dict[str, Any]) -> DetectionResult:
    """Turn the model's JSON into a DetectionResult, tolerating missing keys."""
    result = DetectionResult()

    for entry in payload.get("speeches") or []:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).strip().upper()
        marker = str(entry.get("start_marker", "") or "")
        if not label or not marker.strip():
            continue
        speaker = entry.get("speaker")
        slot = slot_for(label)
        result.speeches.append(
            DetectedSpeech(
                label=label,
                speaker=(slot.speaker if slot else (str(speaker) if speaker else None)),
                start_marker=marker,
            )
        )

    resolution = payload.get("resolution") or {}
    if isinstance(resolution, dict):
        text = resolution.get("text")
        result.resolution_text = str(text).strip() if text else None
        quote = resolution.get("quote")
        result.resolution_quote = str(quote).strip() if quote else None
        result.resolution_confidence = str(
            resolution.get("confidence") or "low"
        ).lower()

    notes = payload.get("notes")
    result.notes = str(notes).strip() if notes else ""
    return result


def missing_speeches(found: List[str], debate_format: str = "LD") -> List[str]:
    """Canonical labels absent from a detection result."""
    seen = set(found)
    return [label for label in expected_labels(debate_format) if label not in seen]


def mismatch_message(found_count: int, missing: List[str], expected: int = 7) -> str:
    """Story 2.1's mismatch prompt, worded as the acceptance criteria specify."""
    detail = f" Missing: {', '.join(missing)}." if missing else ""
    return (
        f"Expected {expected} speeches, found {found_count}.{detail} Proceed anyway?"
    )


def detect_structure(
    client,
    transcript: str,
    debate_format: str = "LD",
    write_segments: bool = True,
) -> Tuple[DetectionResult, List[LabeledSpeech]]:
    """
    Run detection and return both the raw result and split, labeled speeches.

    `client` needs only an `invoke()` method, so the dry-run and fake clients
    work here unchanged.
    """
    response = client.invoke(
        system=load_prompt(DETECTION_PROMPT),
        user=transcript,
        max_tokens=DETECTION_MAX_TOKENS,
        temperature=DETECTION_TEMPERATURE,
    )
    result = parse_detection(extract_json(response.text))

    segments, unmatched = split_transcript(transcript, result.speeches)
    result.unmatched_markers = unmatched
    # Keep only speeches we actually placed, so `labels` and the missing-speech
    # warning describe what was really split rather than what was proposed.
    result.speeches = [speech for speech, _content in segments]
    if segments:
        result.preamble_chars = segments[0][0].start_index or 0

    speeches: List[LabeledSpeech] = []
    if write_segments:
        for detected, content in segments:
            slot = slot_for(detected.label, debate_format)
            speeches.append(
                LabeledSpeech(
                    path=_InMemorySegment(detected.label, content),
                    label=detected.label,
                    speaker=detected.speaker or (slot.speaker if slot else None),
                    position=slot.position if slot else None,
                    source=SOURCE_MODEL,
                )
            )
    return result, speeches


class _InMemorySegment:
    """
    Path-like holder for a segment that exists only in memory.

    Detection splits one file into several speeches, so downstream code that
    expects `speech.path.read_text()` needs something to read from without
    writing seven temp files.
    """

    def __init__(self, label: str, content: str):
        self._label = label
        self._content = content

    @property
    def name(self) -> str:
        return f"{self._label} (detected)"

    @property
    def stem(self) -> str:
        return self._label

    def read_text(self, *_args, **_kwargs) -> str:
        return self._content

    def __fspath__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<segment {self._label}: {len(self._content)} chars>"


# --- Story 2.4: resolution auto-detection across files -----------------

# Below this, a detected resolution isn't worth showing the user.
MIN_RESOLUTION_CONFIDENCE = ("high", "medium")


@dataclass
class ResolutionCandidate:
    """A resolution one file's detection pass produced."""

    text: str
    source_label: str          # e.g. "1AC", or the filename
    confidence: str = "low"
    quote: Optional[str] = None


def resolutions_align(first: str, second: str) -> bool:
    """
    Whether two candidates are the same resolution.

    Trivial differences — punctuation, capitalization, a "Resolved:" prefix —
    don't count as disagreement.
    """
    return _resolution_key(first) == _resolution_key(second)


def _resolution_key(text: str) -> str:
    stripped = re.sub(r"^\s*resolved\s*[:,]?\s*", "", text.strip(), flags=re.I)
    return _normalize(stripped)


def reconcile_resolutions(
    candidates: List[ResolutionCandidate],
) -> Tuple[Optional[ResolutionCandidate], List[ResolutionCandidate]]:
    """
    Collapse per-file candidates into one, or report the disagreement.

    Returns (agreed, conflicts). When everything aligns, `agreed` is the
    highest-confidence phrasing and `conflicts` is empty. When candidates
    genuinely differ, `agreed` is None and `conflicts` holds one representative
    per distinct resolution, in first-seen order (Story 2.4 prompts [a/b/...]).
    """
    usable = [
        candidate for candidate in candidates
        if candidate.text and candidate.confidence in MIN_RESOLUTION_CONFIDENCE
    ]
    if not usable:
        return None, []

    groups: List[List[ResolutionCandidate]] = []
    for candidate in usable:
        for group in groups:
            if resolutions_align(group[0].text, candidate.text):
                group.append(candidate)
                break
        else:
            groups.append([candidate])

    if len(groups) == 1:
        # Prefer a high-confidence phrasing over a medium one.
        best = sorted(
            groups[0], key=lambda c: 0 if c.confidence == "high" else 1
        )[0]
        return best, []

    return None, [group[0] for group in groups]


def conflict_prompt(conflicts: List[ResolutionCandidate]) -> str:
    """Story 2.4's disagreement prompt, worded as the criteria specify."""
    lines = ["Detected different resolutions across speech files:"]
    for index, candidate in enumerate(conflicts):
        letter = chr(ord("a") + index)
        lines.append(f"  ({letter}) From {candidate.source_label}: '{candidate.text}'")
    letters = "/".join(chr(ord("a") + i) for i in range(len(conflicts)))
    lines.append(f"Which one is correct? [{letters}/edit/skip]")
    return "\n".join(lines)


def confirm_prompt(candidate: ResolutionCandidate) -> str:
    return f"Detected resolution: '{candidate.text}' Use this? [Y/edit/skip]"


NO_RESOLUTION_MESSAGE = "Could not auto-detect resolution."
