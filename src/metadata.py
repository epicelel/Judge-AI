"""
Round metadata: resolution, Aff speaker, Neg speaker (Story 1.3).

All three fields are optional. Ballots fall back to generic "Aff"/"Neg" labels
and simply don't quote a resolution when it isn't known.

Precedence, highest first (Story 2.4):
  1. round.yaml sidecar     — never overridden
  2. --resolution CLI flag  — beats auto-detection
  3. auto-detected value    — from the structure-detection pass (Story 2.4)
  4. interactive prompt     — last resort, and skippable with Enter

Provenance is recorded per field so metadata.json shows where each value came
from, and so an auto-detected value that lost to the yaml is still visible
rather than silently discarded.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Callable, Dict, Optional, Sequence

import yaml

from .documents import read_transcript_text
from .ingest import IngestError

# Field names as they appear in round.yaml, matched case-insensitively.
YAML_FIELDS = ("resolution", "aff", "neg")

DEFAULT_AFF_LABEL = "Aff"
DEFAULT_NEG_LABEL = "Neg"

PROMPTS = {
    "resolution": "Resolution",
    "aff": "Aff speaker name",
    "neg": "Neg speaker name",
}

# Provenance values recorded in `sources`.
SOURCE_YAML = "round.yaml"
SOURCE_FLAG = "--resolution flag"
SOURCE_DETECTED = "auto-detected"
SOURCE_TRANSCRIPT = "transcript-detected"
SOURCE_PROMPT = "prompted"
SOURCE_SKIPPED = "skipped"


# Explicit participant labels commonly found in transcript headers.  These are
# intentionally conservative: a false speaker name is worse than falling back to
# the generic Aff/Neg labels.
_SIDE_ALIASES = {
    "aff": "aff",
    "affirmative": "aff",
    "pro": "aff",
    "prop": "aff",
    "proposition": "aff",
    "neg": "neg",
    "negative": "neg",
    "con": "neg",
    "opp": "neg",
    "opposition": "neg",
}

_GENERIC_PARTICIPANTS = {
    "aff", "affirmative", "affirmative speaker", "affirmative team",
    "pro", "prop", "proposition", "proposition team",
    "neg", "negative", "negative speaker", "negative team",
    "con", "opp", "opposition", "opposition team",
    "speaker", "unknown", "n/a", "na", "tbd",
}

# "Aff: Eliana", "Affirmative Speaker - Eliana", and combined lines such as
# "Aff: Eliana | Neg: Marcus".
_SIDE_THEN_NAME = re.compile(
    r"(?i)(?:^|[|;])\s*"
    r"(aff(?:irmative)?|pro(?:position)?|prop|neg(?:ative)?|con|opp(?:osition)?)"
    r"(?:\s+(?:speaker|debater|team))?\s*[:=\-]\s*([^|;\r\n]+)"
)

# Templates also appear as "Eliana: Aff" or "George & Ryan: Pro".
_NAME_THEN_SIDE = re.compile(
    r"(?i)^\s*([^|;:\r\n]{1,80}?)\s*[:=\-]\s*"
    r"(aff(?:irmative)?|pro(?:position)?|prop|neg(?:ative)?|con|opp(?:osition)?)"
    r"(?:\s+(?:speaker|debater|team))?\s*$"
)

_SELF_INTRO = re.compile(
    r"(?i)\bmy\s+name(?:\s+is|'s|’s)\s+"
    r"([A-Za-z][A-Za-z'’.-]*(?:\s+[A-Za-z][A-Za-z'’.-]*){0,5})"
)

_INTRO_STOPWORDS = {
    "and", "but", "today", "i", "we", "will", "am", "affirm", "affirming",
    "negate", "negating", "represent", "representing", "from", "here", "your",
    "the", "this", "our", "on", "for",
}


def _side_key(label: str) -> Optional[str]:
    """Normalize an Aff/Neg/Pro/Con-style side word to ``aff`` or ``neg``."""
    lowered = re.sub(r"[^a-z]", "", str(label).lower())
    if lowered.startswith("affirmative"):
        lowered = "affirmative"
    elif lowered.startswith("negative"):
        lowered = "negative"
    elif lowered.startswith("proposition"):
        lowered = "proposition"
    elif lowered.startswith("opposition"):
        lowered = "opposition"
    return _SIDE_ALIASES.get(lowered)


def _clean_participant(value: str) -> Optional[str]:
    """Return a plausible participant/team name or ``None`` when it is generic."""
    if not value:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip(" \t\r\n-:;|[]{}()\"'")
    # Remove a trailing role annotation such as "Eliana (Aff)".
    text = re.sub(
        r"(?i)\s*[\[(]\s*(?:aff(?:irmative)?|pro(?:position)?|prop|"
        r"neg(?:ative)?|con|opp(?:osition)?)\s*[\])]\s*$",
        "",
        text,
    ).strip()
    if not text or len(text) > 80:
        return None
    if text.lower() in _GENERIC_PARTICIPANTS:
        return None
    # Long prose after a colon is almost certainly not a name/team label.
    if len(text.split()) > 8:
        return None
    return text


def _header_participants(text: str) -> Dict[str, str]:
    """Extract explicit side/name pairs from transcript/template header lines."""
    found: Dict[str, str] = {}
    for line in text.splitlines():
        if len(found) == 2:
            break
        # A single line may contain both sides: ``Aff: A | Neg: B``.
        for match in _SIDE_THEN_NAME.finditer(line):
            side = _side_key(match.group(1))
            name = _clean_participant(match.group(2))
            if side and name and side not in found:
                found[side] = name
        if len(found) == 2:
            break
        match = _NAME_THEN_SIDE.match(line)
        if match:
            name = _clean_participant(match.group(1))
            side = _side_key(match.group(2))
            if side and name and side not in found:
                found[side] = name
    return found


def _self_intro_name(text: str) -> Optional[str]:
    """Read a conservative ``my name is ...`` introduction near a speech start."""
    match = _SELF_INTRO.search(text[:1800])
    if not match:
        return None
    words = match.group(1).split()
    kept = []
    for word in words:
        normalized = re.sub(r"[^a-z]", "", word.lower())
        if kept and normalized in _INTRO_STOPWORDS:
            break
        kept.append(word)
    return _clean_participant(" ".join(kept))


def _speech_side(label: Optional[str]) -> Optional[str]:
    if label in {"1AC", "1AR", "2AR"}:
        return "aff"
    if label in {"1NC", "2NR"}:
        return "neg"
    return None


def _speech_text(speech) -> str:
    source = getattr(speech, "path", None)
    if source is None:
        return ""
    try:
        if isinstance(source, Path):
            return read_transcript_text(source)
        return source.read_text()
    except (OSError, AttributeError):
        return ""


def detect_participant_names(
    files: Sequence[Path],
    speeches: Sequence[object] = (),
) -> Dict[str, Optional[str]]:
    """
    Detect Aff/Neg participant names without an extra model call.

    Priority inside this detector:
      1. explicit transcript/template headers (``Aff: Eliana``)
      2. a ``my name is ...`` introduction in a side-specific LD speech

    The metadata resolver still gives round.yaml higher precedence, so this can
    never overwrite user-supplied metadata. Generic labels such as ``Aff: Aff``
    are deliberately ignored.
    """
    found: Dict[str, str] = {}

    for path in files:
        try:
            text = read_transcript_text(Path(path))
        except Exception:
            continue
        for side, name in _header_participants(text).items():
            found.setdefault(side, name)
        if len(found) == 2:
            break

    if len(found) < 2:
        ordered = sorted(
            speeches,
            key=lambda speech: getattr(speech, "position", None) or 999,
        )
        for speech in ordered:
            side = _speech_side(getattr(speech, "label", None))
            if not side or side in found:
                continue
            name = _self_intro_name(_speech_text(speech))
            if name:
                found[side] = name
            if len(found) == 2:
                break

    return {"aff": found.get("aff"), "neg": found.get("neg")}


@dataclass
class RoundMetadata:
    """Resolved metadata for one round, with per-field provenance."""

    resolution: Optional[str] = None
    aff: Optional[str] = None
    neg: Optional[str] = None
    sources: Dict[str, str] = field(default_factory=dict)
    # An auto-detected resolution that lost to a higher-precedence source.
    # Kept for reference per Story 2.4 rather than thrown away.
    overridden_detection: Optional[str] = None

    @property
    def aff_label(self) -> str:
        """What to call the affirmative in a ballot."""
        return self.aff or DEFAULT_AFF_LABEL

    @property
    def neg_label(self) -> str:
        return self.neg or DEFAULT_NEG_LABEL

    @property
    def has_resolution(self) -> bool:
        return bool(self.resolution)

    def to_dict(self) -> Dict[str, Any]:
        """Shape written into metadata.json."""
        payload: Dict[str, Any] = {
            "resolution": self.resolution,
            "aff": self.aff,
            "neg": self.neg,
            "metadata_sources": self.sources,
        }
        if self.overridden_detection:
            payload["overridden_detection"] = self.overridden_detection
        return payload


def _clean(value: Any) -> Optional[str]:
    """Normalize a metadata value; blank and non-scalar values count as absent."""
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def load_metadata_file(path: Path) -> Dict[str, Optional[str]]:
    """
    Read a round.yaml sidecar.

    Malformed YAML raises rather than being ignored: a typo in a hand-written
    sidecar would otherwise leave the user believing their resolution was used
    when it silently wasn't. Unknown keys are ignored so the format can grow.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise IngestError(
            f"Could not parse {path.name}: {exc}. "
            f"Fix the YAML or delete the file to be prompted instead."
        ) from exc
    except OSError as exc:
        raise IngestError(f"Could not read {path}: {exc}") from exc

    if raw is None:
        return {}  # an empty file is valid YAML and simply means "no metadata"

    if not isinstance(raw, dict):
        raise IngestError(
            f"{path.name} must be a mapping of fields "
            f"({', '.join(YAML_FIELDS)}), not {type(raw).__name__}."
        )

    lowered = {str(key).strip().lower(): value for key, value in raw.items()}
    return {
        name: _clean(lowered.get(name))
        for name in YAML_FIELDS
        if _clean(lowered.get(name)) is not None
    }


def _default_prompt(label: str) -> str:
    """
    Ask for one optional field. Enter returns "" and skips it.

    Unlike the file-count confirmation, absent input is not an error here —
    every field is optional, so a non-interactive run just skips them all.
    """
    import click

    try:
        return click.prompt(label, default="", show_default=False, err=True)
    except (click.Abort, EOFError, OSError):
        return ""


def resolve_metadata(
    yaml_metadata: Optional[Dict[str, Optional[str]]] = None,
    cli_resolution: Optional[str] = None,
    detected_resolution: Optional[str] = None,
    detected_aff: Optional[str] = None,
    detected_neg: Optional[str] = None,
    prompt: Optional[Callable[[str], str]] = None,
) -> RoundMetadata:
    """
    Apply the precedence chain and prompt for whatever is still missing.

    Fields already supplied by a higher-precedence source are never prompted
    for, so a complete round.yaml means no prompts at all.
    """
    supplied = dict(yaml_metadata or {})
    meta = RoundMetadata()

    # --- resolution: yaml > flag > detected > prompt ---
    if _clean(supplied.get("resolution")):
        meta.resolution = _clean(supplied["resolution"])
        meta.sources["resolution"] = SOURCE_YAML
        if detected_resolution:
            meta.overridden_detection = detected_resolution
    elif _clean(cli_resolution):
        meta.resolution = _clean(cli_resolution)
        meta.sources["resolution"] = SOURCE_FLAG
        if detected_resolution:
            meta.overridden_detection = detected_resolution
    elif _clean(detected_resolution):
        meta.resolution = _clean(detected_resolution)
        meta.sources["resolution"] = SOURCE_DETECTED

    # --- speakers: yaml > transcript detection > prompt ---
    detected_speakers = {"aff": _clean(detected_aff), "neg": _clean(detected_neg)}
    for name in ("aff", "neg"):
        if _clean(supplied.get(name)):
            setattr(meta, name, _clean(supplied[name]))
            meta.sources[name] = SOURCE_YAML
        elif detected_speakers[name]:
            setattr(meta, name, detected_speakers[name])
            meta.sources[name] = SOURCE_TRANSCRIPT

    # --- prompt for whatever is left, one field at a time, in order ---
    ask = prompt or _default_prompt
    for name in ("resolution", "aff", "neg"):
        if getattr(meta, name) is not None:
            continue
        answer = _clean(ask(PROMPTS[name]))
        if answer:
            setattr(meta, name, answer)
            meta.sources[name] = SOURCE_PROMPT
        else:
            meta.sources[name] = SOURCE_SKIPPED

    return meta


# --- Story 2.4: turning detected candidates into a confirmed resolution --

ANSWER_SKIP = "skip"
ANSWER_EDIT = "edit"


def confirm_detected_resolution(
    candidates,
    ask: Optional[Callable[[str], str]] = None,
) -> Optional[str]:
    """
    Resolve detected candidates into a resolution the user has accepted.

    Aligned candidates are confirmed with [Y/edit/skip]; genuinely different
    ones are listed for an [a/b/edit/skip] choice. Returning None means "fall
    through to the Story 1.3 prompt".

    `ask` receives the prompt text and returns the raw answer, so the CLI owns
    input and tests inject answers.
    """
    from .detection import (
        NO_RESOLUTION_MESSAGE,
        confirm_prompt,
        conflict_prompt,
        reconcile_resolutions,
    )

    agreed, conflicts = reconcile_resolutions(list(candidates))
    respond = ask or _default_prompt

    if agreed is None and not conflicts:
        return None  # nothing usable; caller reports NO_RESOLUTION_MESSAGE

    if agreed is not None:
        answer = (respond(confirm_prompt(agreed)) or "").strip().lower()
        if answer in ("", "y", "yes"):
            return agreed.text
        if answer == ANSWER_EDIT:
            return _clean(respond("Resolution"))
        return None  # skip

    answer = (respond(conflict_prompt(conflicts)) or "").strip().lower()
    if answer == ANSWER_EDIT:
        return _clean(respond("Resolution"))
    if len(answer) == 1 and "a" <= answer <= chr(ord("a") + len(conflicts) - 1):
        return conflicts[ord(answer) - ord("a")].text
    return None  # skip, or an unrecognized answer
