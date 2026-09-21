"""Operations on already-saved JudgeAI rounds.

This module keeps history/retry logic out of the desktop UI so it can be tested
without PyQt and reused by the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Dict, List, Optional

from .judging import (
    PARADIGMS,
    JudgingResult,
    extract_flow,
    generate_diff,
    judge_round,
    needs_flow,
)
from .storage import LocalDiskBallotStore, StorageError


@dataclass
class _SavedBallot:
    text: str


@dataclass
class SavedVerdict:
    paradigm: str
    winner: Optional[str]
    label: str
    display_vote_share: str
    representative: Optional[_SavedBallot]
    failed: bool = False
    unavailable_runs: int = 0

    @property
    def ok(self) -> bool:
        return not self.failed and self.representative is not None and bool(self.winner)


@dataclass
class SavedResult:
    verdicts: List[SavedVerdict]

    @property
    def successful(self) -> List[SavedVerdict]:
        return [v for v in self.verdicts if v.ok]

    @property
    def failures(self) -> List[SavedVerdict]:
        return [v for v in self.verdicts if not v.ok]

    @property
    def unanimous(self) -> bool:
        winners = {v.winner for v in self.successful}
        return bool(winners) and len(winners) == 1


def _fallback_decision_parts(decision: str) -> tuple[Optional[str], str, str]:
    decision = (decision or "").strip()
    winner_match = re.match(r"^(AFF|NEG)\b", decision, re.I)
    winner = winner_match.group(1).upper() if winner_match else None
    share_match = re.search(r"\(([^)]*)\)", decision)
    share = share_match.group(1) if share_match else "?/?"
    lowered = decision.lower()
    if "slight lean" in lowered:
        label = "slight lean"
    elif "clear" in lowered:
        label = "clear"
    else:
        label = "toss-up"
    return winner, label, share


def reconstruct_saved_result(
    store: LocalDiskBallotStore,
    round_id: str,
    metadata: Optional[dict] = None,
) -> SavedResult:
    """Reconstruct the minimum result shape needed by cross-paradigm synthesis."""
    metadata = metadata or store.load_metadata(round_id)
    usage = metadata.get("token_usage") or {}
    decisions = metadata.get("decisions") or {}
    keys = []
    for key in PARADIGMS:
        if key in usage or key in decisions or key in metadata.get("paradigms", []):
            keys.append(key)
    for key in metadata.get("failed_paradigms", []):
        if key in PARADIGMS and key not in keys:
            keys.append(key)

    verdicts: List[SavedVerdict] = []
    for key in keys:
        entry = usage.get(key) if isinstance(usage.get(key), dict) else {}
        winner = entry.get("winner")
        label = entry.get("label")
        display_share = entry.get("display_vote_share") or entry.get("vote_share")
        unavailable = int(entry.get("unavailable_runs") or 0)
        failed = bool(entry.get("failed", False))

        if not winner or not label or not display_share:
            fallback_winner, fallback_label, fallback_share = _fallback_decision_parts(
                decisions.get(key, "")
            )
            winner = winner or fallback_winner
            label = label or fallback_label
            display_share = display_share or fallback_share

        ballot = None
        try:
            ballot = _SavedBallot(store.load_ballot(round_id, key))
        except StorageError:
            failed = True

        verdicts.append(
            SavedVerdict(
                paradigm=key,
                winner=winner,
                label=label or "toss-up",
                display_vote_share=display_share or "?/?",
                representative=ballot,
                failed=failed or ballot is None or winner is None,
                unavailable_runs=unavailable,
            )
        )
    return SavedResult(verdicts)


def retry_analysis(
    client,
    store: LocalDiskBallotStore,
    round_id: str,
) -> dict:
    """Regenerate only the cross-paradigm synthesis for a saved round.

    Existing paradigm ballots are reused exactly as saved. No paradigm is
    rejudged, so this costs only one synthesis model call.
    """
    metadata = store.load_metadata(round_id)
    saved_result = reconstruct_saved_result(store, round_id, metadata)

    if len(saved_result.successful) < 2:
        raise ValueError(
            "Cross-paradigm analysis needs at least two successful saved paradigms."
        )

    response = generate_diff(
        client=client,
        round_id=round_id,
        date=metadata.get("date") or datetime.now().strftime("%Y-%m-%d"),
        resolution=metadata.get("resolution"),
        aff=metadata.get("aff") or "Aff",
        neg=metadata.get("neg") or "Neg",
        result=saved_result,
    )
    store.save_diff(round_id, response.text)

    usage = metadata.setdefault("token_usage", {})
    usage["diff"] = {
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "cost_usd": round(response.cost_usd, 6),
    }

    metadata["total_input_tokens"] = (
        int(metadata.get("total_input_tokens") or 0) + response.input_tokens
    )
    metadata["total_output_tokens"] = (
        int(metadata.get("total_output_tokens") or 0) + response.output_tokens
    )
    metadata["total_cost_usd"] = round(
        float(metadata.get("total_cost_usd") or 0) + response.cost_usd,
        6,
    )
    metadata.setdefault("analysis_retry_history", []).append(
        {
            "date": datetime.now().isoformat(timespec="seconds"),
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cost_usd": round(response.cost_usd, 6),
        }
    )
    store.save_metadata(round_id, metadata)

    return {
        "round_id": round_id,
        "text": response.text,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "cost_usd": response.cost_usd,
    }


def retry_paradigm(
    client,
    store: LocalDiskBallotStore,
    round_id: str,
    paradigm_key: str,
    runs: int = 3,
) -> dict:
    """Rejudge one paradigm in place, then regenerate the round diff.

    Existing ballots for the other paradigms are retained. The selected
    paradigm's representative ballot, decision, usage and run count are replaced.
    """
    if paradigm_key not in PARADIGMS:
        raise ValueError(f"Unknown paradigm: {paradigm_key}")

    metadata = store.load_metadata(round_id)
    structured = store.load_transcript(round_id)

    flow_text = None
    flow_response = None
    if needs_flow([paradigm_key]):
        try:
            flow_text = store.load_flow(round_id)
        except StorageError:
            flow_response = extract_flow(client, structured)
            flow_text = flow_response.text
            store.save_flow(round_id, flow_text)

    result: JudgingResult = judge_round(
        client,
        structured,
        [paradigm_key],
        store=store,
        round_id=round_id,
        flow_text=flow_text,
        runs=runs,
    )
    verdict = result.verdicts[0]

    usage = metadata.setdefault("token_usage", {})
    usage[paradigm_key] = verdict.usage()
    decisions = metadata.setdefault("decisions", {})
    decisions[paradigm_key] = verdict.decision
    runs_by = metadata.setdefault("runs_by_paradigm", {})
    runs_by[paradigm_key] = runs

    successful = set(metadata.get("paradigms") or [])
    failed = set(metadata.get("failed_paradigms") or [])
    if verdict.ok:
        successful.add(paradigm_key)
        failed.discard(paradigm_key)
    else:
        successful.discard(paradigm_key)
        failed.add(paradigm_key)
    metadata["paradigms"] = [key for key in PARADIGMS if key in successful]
    metadata["failed_paradigms"] = [key for key in PARADIGMS if key in failed]

    if flow_response is not None:
        usage["flow"] = {
            "input_tokens": flow_response.input_tokens,
            "output_tokens": flow_response.output_tokens,
            "cost_usd": round(flow_response.cost_usd, 6),
        }

    # Totals represent cumulative API spend for the round, including retries.
    # Do not subtract the replaced ballot's historical spend; that money was still
    # spent. This also keeps older metadata accurate even when it did not break flow
    # and diff usage out into separate token_usage entries.
    added_input = verdict.input_tokens
    added_output = verdict.output_tokens
    added_cost = verdict.cost_usd
    if flow_response is not None:
        added_input += flow_response.input_tokens
        added_output += flow_response.output_tokens
        added_cost += flow_response.cost_usd
    metadata["total_input_tokens"] = int(metadata.get("total_input_tokens") or 0) + added_input
    metadata["total_output_tokens"] = int(metadata.get("total_output_tokens") or 0) + added_output
    metadata["total_cost_usd"] = round(float(metadata.get("total_cost_usd") or 0) + added_cost, 6)
    metadata.setdefault("retry_history", []).append(
        {
            "paradigm": paradigm_key,
            "runs": runs,
            "decision": verdict.decision,
            "input_tokens": added_input,
            "output_tokens": added_output,
            "cost_usd": round(added_cost, 6),
        }
    )
    store.save_metadata(round_id, metadata)

    # Regenerate the comparison only when at least two representative ballots exist.
    saved_result = reconstruct_saved_result(store, round_id, metadata)
    if len(saved_result.successful) >= 2:
        diff_response = generate_diff(
            client=client,
            round_id=round_id,
            date=metadata.get("date") or datetime.now().strftime("%Y-%m-%d"),
            resolution=metadata.get("resolution"),
            aff=metadata.get("aff") or "Aff",
            neg=metadata.get("neg") or "Neg",
            result=saved_result,
        )
        store.save_diff(round_id, diff_response.text)
        usage["diff"] = {
            "input_tokens": diff_response.input_tokens,
            "output_tokens": diff_response.output_tokens,
            "cost_usd": round(diff_response.cost_usd, 6),
        }
        metadata["total_input_tokens"] += diff_response.input_tokens
        metadata["total_output_tokens"] += diff_response.output_tokens
        metadata["total_cost_usd"] = round(
            float(metadata.get("total_cost_usd") or 0) + diff_response.cost_usd, 6
        )
        metadata["retry_history"][-1]["input_tokens"] += diff_response.input_tokens
        metadata["retry_history"][-1]["output_tokens"] += diff_response.output_tokens
        metadata["retry_history"][-1]["cost_usd"] = round(
            float(metadata["retry_history"][-1]["cost_usd"]) + diff_response.cost_usd, 6
        )
        store.save_metadata(round_id, metadata)

    return {
        "round_id": round_id,
        "paradigm": paradigm_key,
        "decision": verdict.decision,
        "success": verdict.ok,
        "unavailable_runs": verdict.unavailable_runs,
    }
