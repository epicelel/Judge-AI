from pathlib import Path
from types import SimpleNamespace

from src.round_ops import retry_analysis
from src.storage import LocalDiskBallotStore


def test_retry_analysis_reuses_saved_ballots_without_rejudging(tmp_path: Path, monkeypatch):
    store = LocalDiskBallotStore(tmp_path)
    round_id = "654321.010126.topic.alice"

    store.save_ballot(
        round_id,
        "lay",
        "WINNER: AFF\nLEAN: clear\nRFD: reason\nSPEAKER POINTS: Aff 29 / Neg 28",
    )
    store.save_ballot(
        round_id,
        "traditional",
        "WINNER: NEG\nLEAN: clear\nRFD: reason\nSPEAKER POINTS: Aff 28 / Neg 29",
    )
    store.save_metadata(
        round_id,
        {
            "date": "2026-01-01",
            "resolution": "R",
            "aff": "Alice",
            "neg": "Bob",
            "paradigms": ["lay", "traditional"],
            "failed_paradigms": [],
            "decisions": {
                "lay": "AFF (1/1) clear",
                "traditional": "NEG (1/1) clear",
            },
            "token_usage": {
                "lay": {
                    "winner": "AFF",
                    "label": "clear",
                    "display_vote_share": "1/1",
                    "unavailable_runs": 0,
                },
                "traditional": {
                    "winner": "NEG",
                    "label": "clear",
                    "display_vote_share": "1/1",
                    "unavailable_runs": 0,
                },
            },
            "total_input_tokens": 100,
            "total_output_tokens": 50,
            "total_cost_usd": 0.01,
        },
    )

    calls = []

    def fake_generate_diff(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            text="=== JudgeAI — Cross-Paradigm Diff ===\nRecovered",
            input_tokens=20,
            output_tokens=10,
            cost_usd=0.002,
        )

    monkeypatch.setattr("src.round_ops.generate_diff", fake_generate_diff)

    result = retry_analysis(object(), store, round_id)

    assert len(calls) == 1
    assert result["round_id"] == round_id
    assert "Recovered" in store.load_diff(round_id)

    metadata = store.load_metadata(round_id)
    assert metadata["total_input_tokens"] == 120
    assert metadata["total_output_tokens"] == 60
    assert metadata["total_cost_usd"] == 0.012
    assert metadata["analysis_retry_history"][-1]["cost_usd"] == 0.002

from click.testing import CliRunner

from src.cli import cli


def test_retry_analysis_command_is_exposed():
    result = CliRunner().invoke(cli, ["retry-analysis", "--help"])
    assert result.exit_code == 0
    assert "cross-paradigm" in result.output.lower()
