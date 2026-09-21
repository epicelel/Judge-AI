from pathlib import Path

from src.round_ops import reconstruct_saved_result
from src.storage import LocalDiskBallotStore


def test_reconstruct_saved_result_uses_saved_usage(tmp_path: Path):
    store = LocalDiskBallotStore(tmp_path)
    round_id = "123456.010126.topic.aff"
    store.save_ballot(round_id, "lay", "WINNER: AFF\nLEAN: clear\nRFD: reason\nSPEAKER POINTS: Aff 29 / Neg 28")
    store.save_ballot(round_id, "circuit", "WINNER: NEG\nLEAN: clear\nRFD: reason\nSPEAKER POINTS: Aff 28 / Neg 29")
    metadata = {
        "paradigms": ["lay", "circuit"],
        "decisions": {"lay": "AFF (2/3) slight lean", "circuit": "NEG (3/3) clear"},
        "token_usage": {
            "lay": {"winner": "AFF", "label": "slight lean", "display_vote_share": "2/3", "unavailable_runs": 0},
            "circuit": {"winner": "NEG", "label": "clear", "display_vote_share": "3/3", "unavailable_runs": 0},
        },
    }
    store.save_metadata(round_id, metadata)
    result = reconstruct_saved_result(store, round_id)
    assert len(result.successful) == 2
    assert {v.winner for v in result.successful} == {"AFF", "NEG"}
    assert result.unanimous is False


def test_retry_paradigm_replaces_one_ballot_and_refreshes_diff(tmp_path, make_fake_bedrock):
    from tests.conftest import BALLOT_STUB, DIFF_STUB
    from src.round_ops import retry_paradigm

    store = LocalDiskBallotStore(tmp_path)
    round_id = "654321.010126.topic.aff"
    store.save_transcript(round_id, "=== 1AC ===\nAff case\n=== 1NC ===\nNeg case")
    store.save_flow(round_id, "A. FRAMEWORKS\nNone")
    store.save_ballot(round_id, "lay", BALLOT_STUB)
    store.save_ballot(round_id, "traditional", BALLOT_STUB.replace("WINNER: AFF", "WINNER: NEG"))
    store.save_metadata(
        round_id,
        {
            "date": "2026-01-01",
            "resolution": "R",
            "aff": "A",
            "neg": "N",
            "paradigms": ["lay", "traditional"],
            "failed_paradigms": [],
            "decisions": {"lay": "AFF (1/1) clear", "traditional": "NEG (1/1) clear"},
            "token_usage": {
                "lay": {"winner": "AFF", "label": "clear", "display_vote_share": "1/1", "unavailable_runs": 0},
                "traditional": {"winner": "NEG", "label": "clear", "display_vote_share": "1/1", "unavailable_runs": 0},
            },
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0,
        },
    )
    client = make_fake_bedrock(responses=[BALLOT_STUB, BALLOT_STUB, BALLOT_STUB, DIFF_STUB])
    result = retry_paradigm(client, store, round_id, "traditional", runs=3)
    assert result["success"] is True
    metadata = store.load_metadata(round_id)
    assert metadata["decisions"]["traditional"].startswith("AFF")
    assert metadata["runs_by_paradigm"]["traditional"] == 3
    assert metadata["retry_history"][-1]["paradigm"] == "traditional"
    assert "Cross-Paradigm Diff" in store.load_diff(round_id)
