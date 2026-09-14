#!/usr/bin/env python3
"""
Regenerate diffs for all past rounds to add v0.3 strategic recommendations.
Reuses existing ballots, only regenerates the diff (1 API call per round).
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.bedrock_client import build_client
from src.judging import generate_diff, PARADIGMS
from src.storage import LocalDiskBallotStore


@dataclass
class SimpleBallot:
    """Minimal ballot representation for diff regeneration."""
    text: str


@dataclass
class SimpleVerdict:
    """Minimal verdict representation for diff regeneration."""
    paradigm: str
    winner: str
    vote_share: str
    label: str
    representative: SimpleBallot
    _failed: bool = False

    @property
    def failed(self) -> bool:
        return self._failed

    @property
    def ok(self) -> bool:
        return not self._failed


@dataclass
class SimpleResult:
    """Minimal result representation for diff regeneration."""
    verdicts: list
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def successful(self):
        """Return list of non-failed verdicts."""
        return [v for v in self.verdicts if v.ok]

    @property
    def unanimous(self) -> bool:
        """Check if all successful verdicts have same winner."""
        winners = {v.winner for v in self.successful}
        return len(winners) == 1


def reconstruct_result(round_path, metadata):
    """Reconstruct minimal result from saved metadata and ballots."""
    verdicts = []

    for paradigm_key in metadata.get("paradigms", []):
        # Load the ballot file
        ballot_file = round_path / PARADIGMS[paradigm_key].ballot_filename
        if not ballot_file.exists():
            print(f"  ⚠️  Skipping {paradigm_key} (ballot not found)")
            continue

        ballot_text = ballot_file.read_text(encoding="utf-8")

        # Parse decision from metadata (might not exist in old rounds)
        decisions = metadata.get("decisions", {})
        if not decisions:
            print(f"  ⚠️  No decisions in metadata, skipping")
            return None

        decision = decisions.get(paradigm_key, "")
        if not decision:
            print(f"  ⚠️  No decision for {paradigm_key}, skipping")
            continue

        # Format: "AFF (3/3) clear" or "NEG (2/3) slight lean NEG"
        parts = decision.split()
        if len(parts) >= 3:
            winner = parts[0]  # AFF or NEG
            vote_share = parts[1].strip("()")  # 3/3 or 2/3
            label = " ".join(parts[2:])  # "clear" or "slight lean NEG"
        else:
            print(f"  ⚠️  Bad decision format for {paradigm_key}: {decision}")
            continue

        # Create simple objects
        ballot = SimpleBallot(text=ballot_text)
        verdict = SimpleVerdict(
            paradigm=paradigm_key,
            winner=winner,
            vote_share=vote_share,
            label=label,
            representative=ballot,
            _failed=False
        )

        verdicts.append(verdict)

    if not verdicts:
        return None

    # Create simple result
    result = SimpleResult(
        verdicts=verdicts,
        input_tokens=metadata.get("total_input_tokens", 0),
        output_tokens=metadata.get("total_output_tokens", 0),
        cost_usd=metadata.get("total_cost_usd", 0.0)
    )

    return result


def main():
    store = LocalDiskBallotStore()
    client = build_client()

    rounds = store.list_rounds()
    print(f"Found {len(rounds)} rounds\n")

    success_count = 0
    skip_count = 0

    for i, round_data in enumerate(rounds, 1):
        round_id = round_data["round_id"]
        short_id = round_id[:12]
        resolution = round_data.get("resolution") or "Unknown"
        resolution_short = resolution[:50] if resolution else "Unknown"

        print(f"[{i}/{len(rounds)}] {short_id}... {resolution_short}")

        # Load metadata
        round_path = store.round_path(round_id)
        metadata_file = round_path / "metadata.json"

        if not metadata_file.exists():
            print(f"  ⚠️  No metadata.json, skipping")
            skip_count += 1
            continue

        metadata = json.loads(metadata_file.read_text())

        # Reconstruct result from saved data
        try:
            result = reconstruct_result(round_path, metadata)
            if result is None:
                skip_count += 1
                continue
        except Exception as e:
            print(f"  ❌ Failed to reconstruct: {e}")
            skip_count += 1
            continue

        # Regenerate diff with v0.3 prompt
        try:
            diff_response = generate_diff(
                client=client,
                round_id=round_id,
                date=metadata.get("date") or datetime.now().strftime("%Y-%m-%d"),
                resolution=metadata.get("resolution"),
                aff=metadata.get("aff", "Aff"),
                neg=metadata.get("neg", "Neg"),
                result=result
            )

            # Save updated diff
            diff_file = round_path / "diff.md"
            diff_file.write_text(diff_response.text, encoding="utf-8")

            # Check if it has strategic recommendations
            has_strategy = "STRATEGIC RECOMMENDATIONS" in diff_response.text
            status = "✅" if has_strategy else "⚠️ "
            print(f"  {status} Diff regenerated")
            success_count += 1

        except Exception as e:
            print(f"  ❌ Failed to regenerate diff: {e}")
            skip_count += 1
            continue

    print(f"\n✅ Done! Regenerated {success_count} diffs, skipped {skip_count}")


if __name__ == "__main__":
    main()
