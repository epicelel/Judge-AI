"""Small, testable helpers used by the JudgeAI desktop GUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Optional

from .documents import read_transcript_text
from .metadata import detect_participant_names


_RESOLUTION_PATTERNS = (
    re.compile(r"(?im)^\s*(?:resolution|resolved|motion)\s*[:\-]\s*[\"“]?(.+?)[\"”]?\s*$"),
    re.compile(r"(?im)^\s*(?:the\s+)?resolution\s+(?:for\s+this\s+round\s+)?(?:is|reads?)\s*[\":\-]*\s*(.+?)\s*$"),
)


@dataclass(frozen=True)
class PreflightInfo:
    path: Path
    debate_format: str
    resolution: Optional[str]
    aff: Optional[str]
    neg: Optional[str]
    chars: int


def _clean_resolution(value: str) -> Optional[str]:
    text = re.sub(r"\s+", " ", (value or "")).strip(" \t\r\n\"'“”")
    if not text or len(text) < 8 or len(text) > 500:
        return None
    return text


def detect_resolution_locally(text: str) -> Optional[str]:
    """Conservatively detect an explicitly labelled resolution without an LLM call."""
    for pattern in _RESOLUTION_PATTERNS:
        match = pattern.search(text[:12000])
        if match:
            value = _clean_resolution(match.group(1))
            if value:
                return value
    return None


def preflight_transcript(path: Path, debate_format: str = "LD") -> PreflightInfo:
    """Read a transcript and derive zero-cost metadata for the setup dialog."""
    path = Path(path)
    text = read_transcript_text(path)
    participants = detect_participant_names([path], ())
    return PreflightInfo(
        path=path,
        debate_format=debate_format,
        resolution=detect_resolution_locally(text),
        aff=participants.get("aff"),
        neg=participants.get("neg"),
        chars=len(text),
    )


def _pricing(provider: str, model: str) -> tuple[float, float]:
    """Approximate input/output price per million tokens for cost preview only."""
    provider = (provider or "").lower()
    model = (model or "").lower()
    if provider == "openai" or "gpt" in model:
        if "gpt-5.6-luna" in model or not model:
            return 0.20, 1.20
        if "gpt-4-turbo" in model:
            return 10.0, 30.0
        if "gpt-4" in model:
            return 30.0, 60.0
        return 0.20, 1.20
    if provider in {"anthropic", "bedrock"} or "claude" in model:
        if "haiku" in model:
            return 1.0, 5.0
        if "opus" in model:
            return 15.0, 75.0
        return 3.0, 15.0
    return 0.20, 1.20


def estimate_cost_usd(
    chars: int,
    paradigms: Iterable[str],
    runs: int,
    provider: str,
    model: str,
) -> tuple[float, float]:
    """Return a rough low/high estimate for one complete GUI round.

    The estimate intentionally uses a range. Prompt length, model tokenization,
    retries, and output verbosity all vary in practice.
    """
    count = max(1, len(list(paradigms)))
    runs = max(1, int(runs))
    base_tokens = max(500, int(chars / 4))
    input_rate, output_rate = _pricing(provider, model)

    # One flow call for technical/educated paradigms, N ballots, and one diff.
    has_flow = count > 0
    flow_in = base_tokens if has_flow else 0
    flow_out = 3500 if has_flow else 0
    ballot_in = base_tokens * count * runs
    ballot_out = 1050 * count * runs
    diff_in = min(18000, 1800 * count + 1200)
    diff_out = 1200 if count >= 2 else 0

    inputs = flow_in + ballot_in + diff_in
    outputs = flow_out + ballot_out + diff_out
    midpoint = inputs / 1_000_000 * input_rate + outputs / 1_000_000 * output_rate
    return max(0.0, midpoint * 0.65), midpoint * 1.55


def combined_report(round_id: str, metadata: dict, diff: str, ballots: dict[str, str]) -> str:
    """Build a portable text/Markdown report from saved round artifacts."""
    resolution = metadata.get("resolution") or "Resolution not detected"
    aff = metadata.get("aff") or "Aff"
    neg = metadata.get("neg") or "Neg"
    date = metadata.get("date") or "Unknown date"

    lines = [
        "# JudgeAI Round Report",
        "",
        f"Round: {round_id}",
        f"Date: {date}",
        f"Resolution: {resolution}",
        f"Aff: {aff}",
        f"Neg: {neg}",
        "",
        "## Cross-Paradigm Analysis",
        "",
        diff.strip() or "No cross-paradigm analysis saved.",
    ]
    for name, content in ballots.items():
        lines += ["", f"## {name}", "", content.strip()]
    return "\n".join(lines).rstrip() + "\n"


def classify_run_error(message: str) -> tuple[str, str]:
    """Turn raw CLI/provider failures into short user-facing GUI messages."""
    text = (message or "").strip()
    lowered = text.lower()
    if "rate limit" in lowered or "429" in lowered or "throttl" in lowered:
        return (
            "Rate limit reached",
            "The model provider is temporarily rate-limiting JudgeAI. Wait a moment and retry the round or failed paradigm.",
        )
    if "api key" in lowered or "credentials" in lowered or "authentication" in lowered:
        return (
            "API key problem",
            "JudgeAI could not authenticate with the selected provider. Open Settings, verify the provider and API key, then retry.",
        )
    if "connection" in lowered or "timed out" in lowered or "timeout" in lowered:
        return (
            "Connection problem",
            "JudgeAI could not reach the model provider. Check your connection and retry.",
        )
    return (
        "Judging failed",
        text or "JudgeAI stopped before the round finished. You can retry without re-importing the transcript.",
    )
