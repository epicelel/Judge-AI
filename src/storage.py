"""
Ballot persistence (Technical Spec §6, Story 5.1).

Everything that touches durable state goes through the BallotStore interface so
the storage backend can be swapped (local disk now, S3 in v0.6+) without
refactoring application code.

Canonical layout:
    ~/Desktop/JudgeAI/Ballots/<Round_ID>/
        metadata.json
        structured_transcript.md
        diff.md                  <- the primary output
        judge_<paradigm>.md      <- one per successful paradigm
"""

import json
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_BALLOTS_ROOT = Path.home() / "Desktop" / "JudgeAI" / "Ballots"

UNKNOWN_RESOLUTION = "unknown-resolution"
UNKNOWN_AFF = "unknown-aff"

# Dropped when building a resolution slug — they carry no identifying signal.
_SLUG_STOPWORDS = {
    "resolved", "the", "a", "an", "of", "is", "are", "was", "be", "been",
    "that", "this", "to", "in", "on", "for", "and", "or", "not", "it",
    "ought", "should", "must", "we", "us", "as", "by", "with", "at",
}

METADATA_FILE = "metadata.json"
DIFF_FILE = "diff.md"
TRANSCRIPT_FILE = "structured_transcript.md"
FLOW_FILE = "flow.md"


class StorageError(Exception):
    """Raised when durable state can't be read or written."""


def slugify(text: Optional[str], max_words: int = 3) -> str:
    """
    Turn free text into a filesystem-safe slug of up to `max_words` keywords.

    "Resolved: The possession of nuclear weapons is immoral."
        -> "possession-nuclear-weapons"
    """
    if not text or not text.strip():
        return ""

    words = re.findall(r"[a-z0-9]+", text.lower())
    keywords = [w for w in words if w not in _SLUG_STOPWORDS]
    # If stopword filtering removed everything, fall back to the raw words so
    # we still produce something more useful than "unknown".
    chosen = (keywords or words)[:max_words]
    return "-".join(chosen)


def _format_date(value: Any) -> str:
    """Render a date as MMDDYY, accepting datetime, YYYY-MM-DD, or None."""
    if isinstance(value, datetime):
        return value.strftime("%m%d%y")
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%m%d%y", "%m/%d/%Y"):
            try:
                return datetime.strptime(value, fmt).strftime("%m%d%y")
            except ValueError:
                continue
    return datetime.now().strftime("%m%d%y")


def generate_round_id(
    metadata: Dict[str, Any],
    existing_ids: Optional[List[str]] = None,
) -> str:
    """
    Build a Round_ID: <6-digit-id>.<MMDDYY>.<resolution-slug>.<aff-slug>

    The 6-digit prefix guarantees uniqueness even when date, resolution, and
    AFF all match (multiple practice rounds in one day). Regenerated on
    collision (Story 5.1).
    """
    taken = {rid.split(".", 1)[0] for rid in (existing_ids or [])}

    date_part = _format_date(metadata.get("date"))
    resolution_part = slugify(metadata.get("resolution")) or UNKNOWN_RESOLUTION
    aff_part = slugify(metadata.get("aff"), max_words=1) or UNKNOWN_AFF

    for _ in range(1000):
        numeric = f"{random.randint(0, 999999):06d}"
        if numeric not in taken:
            return f"{numeric}.{date_part}.{resolution_part}.{aff_part}"

    raise StorageError("Could not generate a unique Round_ID after 1000 tries.")


@dataclass(frozen=True)
class RoundIdParts:
    """The four segments of a Round_ID."""

    numeric: str      # 6-digit uniqueness prefix
    date: str         # MMDDYY
    resolution: str   # slug or "unknown-resolution"
    aff: str          # slug or "unknown-aff"

    @property
    def archive_stem(self) -> str:
        """Filename prefix for archived inputs (Story 1.4)."""
        return f"{self.date}.{self.resolution}.{self.aff}"


def parse_round_id(round_id: str) -> RoundIdParts:
    """
    Split a Round_ID back into its parts.

    Archived input filenames are built from these, so an archived transcript and
    its ballot folder always agree on date, resolution, and speaker instead of
    re-deriving slugs and risking drift.
    """
    segments = round_id.split(".")
    if len(segments) < 4:
        raise StorageError(
            f"Malformed Round_ID '{round_id}': expected "
            f"<6-digit>.<MMDDYY>.<resolution>.<aff>."
        )
    numeric, date_part, resolution, aff = (
        segments[0],
        segments[1],
        ".".join(segments[2:-1]),
        segments[-1],
    )
    return RoundIdParts(numeric, date_part, resolution, aff)


class BallotStore(ABC):
    """Storage interface. Application code depends on this, never on open()."""

    @abstractmethod
    def save_ballot(self, round_id: str, persona: str, content: str) -> None: ...

    @abstractmethod
    def load_ballot(self, round_id: str, persona: str) -> str: ...

    @abstractmethod
    def save_diff(self, round_id: str, content: str) -> None: ...

    @abstractmethod
    def load_diff(self, round_id: str) -> str: ...

    @abstractmethod
    def save_transcript(self, round_id: str, content: str) -> None: ...

    @abstractmethod
    def save_metadata(self, round_id: str, meta: Dict[str, Any]) -> None: ...

    @abstractmethod
    def load_metadata(self, round_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    def list_rounds(self) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def delete_round(self, round_id: str) -> None: ...

    @abstractmethod
    def resolve_round_id(self, partial: str) -> List[str]: ...


class LocalDiskBallotStore(BallotStore):
    """v0.1 default: writes under ~/Desktop/JudgeAI/Ballots/."""

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = Path(base_path) if base_path else DEFAULT_BALLOTS_ROOT

    # --- paths ---------------------------------------------------------

    def round_path(self, round_id: str) -> Path:
        return self.base_path / round_id

    def _ensure_round_dir(self, round_id: str) -> Path:
        path = self.round_path(round_id)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # Story 5.1: the CLI catches this and falls back to stdout so a
            # paid-for run is never lost to a permissions error.
            raise StorageError(f"Cannot write ballots to {path}: {exc}") from exc
        return path

    def _write(self, round_id: str, filename: str, content: str) -> Path:
        path = self._ensure_round_dir(round_id) / filename
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Cannot write {path}: {exc}") from exc
        return path

    def _read(self, round_id: str, filename: str) -> str:
        path = self.round_path(round_id) / filename
        if not path.exists():
            raise StorageError(f"{filename} not found for round '{round_id}'.")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def ballot_filename(persona: str) -> str:
        return f"judge_{persona}.md"

    # --- writes --------------------------------------------------------

    def save_ballot(self, round_id: str, persona: str, content: str) -> None:
        self._write(round_id, self.ballot_filename(persona), content)

    def save_diff(self, round_id: str, content: str) -> None:
        self._write(round_id, DIFF_FILE, content)

    def save_transcript(self, round_id: str, content: str) -> None:
        self._write(round_id, TRANSCRIPT_FILE, content)

    def save_flow(self, round_id: str, content: str) -> None:
        """Persist the flow pass so a ballot's reasoning can be audited."""
        self._write(round_id, FLOW_FILE, content)

    def save_metadata(self, round_id: str, meta: Dict[str, Any]) -> None:
        self._write(round_id, METADATA_FILE, json.dumps(meta, indent=2, default=str))

    # --- reads ---------------------------------------------------------

    def load_ballot(self, round_id: str, persona: str) -> str:
        return self._read(round_id, self.ballot_filename(persona))

    def load_diff(self, round_id: str) -> str:
        return self._read(round_id, DIFF_FILE)

    def load_transcript(self, round_id: str) -> str:
        """Load the saved structured transcript for a round."""
        return self._read(round_id, TRANSCRIPT_FILE)

    def load_flow(self, round_id: str) -> str:
        """Load the saved shared flow for a round."""
        return self._read(round_id, FLOW_FILE)

    def load_metadata(self, round_id: str) -> Dict[str, Any]:
        try:
            return json.loads(self._read(round_id, METADATA_FILE))
        except json.JSONDecodeError as exc:
            raise StorageError(
                f"metadata.json for '{round_id}' is not valid JSON: {exc}"
            ) from exc

    def personas_for(self, round_id: str) -> List[str]:
        """Which paradigms actually produced a ballot, read from disk."""
        path = self.round_path(round_id)
        if not path.exists():
            return []
        return sorted(
            p.stem[len("judge_"):] for p in path.glob("judge_*.md")
        )

    def list_rounds(self) -> List[Dict[str, Any]]:
        """
        Summarize every stored round, newest first (Story 5.2).

        Derived by scanning directories rather than maintaining an index file —
        there is no separate index to drift out of sync with reality.
        """
        if not self.base_path.exists():
            return []

        rounds: List[Dict[str, Any]] = []
        for path in sorted(self.base_path.iterdir()):
            if not path.is_dir():
                continue
            round_id = path.name
            try:
                meta = self.load_metadata(round_id)
            except StorageError:
                meta = {}  # Story 5.2: partial rounds still listed.

            usage = meta.get("token_usage") or {}
            rounds.append(
                {
                    "round_id": round_id,
                    "short_id": round_id.split(".", 1)[0],
                    "date": meta.get("date"),
                    "format": meta.get("format"),
                    "resolution": meta.get("resolution"),
                    "aff": meta.get("aff"),
                    "neg": meta.get("neg"),
                    "paradigms": self.personas_for(round_id),
                    "decisions": meta.get("decisions") or {},
                    "failed_paradigms": meta.get("failed_paradigms") or [],
                    "runs_by_paradigm": meta.get("runs_by_paradigm") or {},
                    "cost_usd": float(
                        meta.get("total_cost_usd")
                        if meta.get("total_cost_usd") is not None
                        else sum(
                            entry.get("cost_usd", 0.0)
                            for entry in usage.values()
                            if isinstance(entry, dict)
                        )
                    ),
                    "has_diff": (path / DIFF_FILE).exists(),
                }
            )

        rounds.sort(key=lambda r: (r["date"] or "", r["round_id"]), reverse=True)
        return rounds

    def resolve_round_id(self, partial: str) -> List[str]:
        """
        Map a user-supplied identifier to stored Round_IDs (Story 5.3).

        Accepts a full Round_ID or just the 6-digit prefix. Returns every match
        so the caller can ask the user to disambiguate when there's more than one.
        """
        if not self.base_path.exists():
            return []
        candidates = [p.name for p in self.base_path.iterdir() if p.is_dir()]
        if partial in candidates:
            return [partial]
        return sorted(
            name for name in candidates
            if name == partial or name.split(".", 1)[0] == partial
            or name.startswith(partial)
        )

    def delete_round(self, round_id: str) -> None:
        """
        Delete a round's ballot folder (Story 5.4).

        Archived input files under Past_Rounds/ are deliberately untouched —
        they are a separate archive the user manages by hand.
        """
        path = self.round_path(round_id)
        if not path.exists():
            raise StorageError(f"Round '{round_id}' not found.")
        for child in sorted(path.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        path.rmdir()
