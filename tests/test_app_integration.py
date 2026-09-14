"""
Integration tests for the Streamlit app (app.py).

These tests verify that app.py calls judging/storage functions with correct
parameters, catching signature mismatches before users hit them.
"""

import sys
from pathlib import Path
from datetime import datetime

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import judging
from src.judging import judge_round, generate_diff, PARADIGMS
from src.storage import generate_round_id, LocalDiskBallotStore
from tests.conftest import FakeBedrockClient


BALLOT = """WINNER: AFF
LEAN: clear
RFD: The affirmative won on the dropped impact.
SPEAKER POINTS: Aff 28 / Neg 27
KEY VOTING ISSUES:
1. Framework
"""


def test_judge_round_parameters_match_app_usage():
    """Verify app.py calls judge_round() with correct parameter names."""
    client = FakeBedrockClient(responses=[BALLOT])

    structured_transcript = """ROUND
Format: LD
Resolution: "Test resolution"
Aff: TestAff | Neg: TestNeg

=== TRANSCRIPT ===
Sample debate text here.
"""

    # This is how app.py calls it - must not raise TypeError
    result = judge_round(
        client=client,
        structured_transcript=structured_transcript,
        paradigms=["lay"],
        runs=1
    )

    assert result is not None
    assert len(result.verdicts) == 1


def test_generate_diff_parameters_match_app_usage():
    """Verify app.py calls generate_diff() with correct parameters."""
    client = FakeBedrockClient(responses=[BALLOT, "DIFF OUTPUT"])

    structured_transcript = """ROUND
Format: LD
Resolution: "Test resolution"
Aff: TestAff | Neg: TestNeg

=== TRANSCRIPT ===
Sample debate text.
"""

    # First judge a round
    result = judge_round(
        client=client,
        structured_transcript=structured_transcript,
        paradigms=["lay"],
        runs=1
    )

    # Then generate diff - this is how app.py calls it
    diff_response = generate_diff(
        client=client,
        round_id="test.123",
        date=datetime.now().strftime("%Y-%m-%d"),
        resolution="Test resolution",
        aff="TestAff",
        neg="TestNeg",
        result=result
    )

    # Should return a ModelResponse with .text attribute
    assert hasattr(diff_response, 'text')
    assert diff_response.text is not None


def test_verdict_has_representative_property():
    """Verify ParadigmVerdict has 'representative' property, not 'ballot'."""
    client = FakeBedrockClient(responses=[BALLOT])

    result = judge_round(
        client=client,
        structured_transcript="ROUND\nFormat: LD\n\n=== TRANSCRIPT ===\nTest",
        paradigms=["lay"],
        runs=1
    )

    verdict = result.verdicts[0]

    # app.py uses verdict.representative.text
    assert hasattr(verdict, 'representative')
    assert verdict.representative is not None
    assert hasattr(verdict.representative, 'text')

    # Should NOT have 'ballot' attribute
    assert not hasattr(verdict, 'ballot')


def test_paradigms_dict_access():
    """Verify PARADIGMS dict can be accessed by key as app.py does."""
    # app.py does: PARADIGMS[verdict.paradigm].ballot_filename
    assert "lay" in PARADIGMS
    assert "circuit" in PARADIGMS

    paradigm = PARADIGMS["lay"]
    assert hasattr(paradigm, 'ballot_filename')
    assert hasattr(paradigm, 'display_name')


def test_generate_round_id_signature():
    """Verify generate_round_id() accepts app.py's call pattern."""
    # This is how app.py calls it
    round_id = generate_round_id(
        {
            "resolution": "Test resolution",
            "aff": "TestAff",
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        existing_ids=[]
    )

    assert round_id is not None
    assert isinstance(round_id, str)


def test_storage_list_rounds():
    """Verify LocalDiskBallotStore.list_rounds() works as app.py expects."""
    store = LocalDiskBallotStore()

    # Should return a list (may be empty if no rounds judged)
    rounds = store.list_rounds()
    assert isinstance(rounds, list)

    # Each round should have expected fields
    if rounds:
        round_data = rounds[0]
        assert "round_id" in round_data
        assert "date" in round_data or round_data.get("date") is None


def test_judging_result_has_token_properties():
    """Verify JudgingResult has input_tokens, output_tokens, cost_usd properties."""
    client = FakeBedrockClient(responses=[BALLOT])

    result = judge_round(
        client=client,
        structured_transcript="ROUND\nFormat: LD\n\n=== TRANSCRIPT ===\nTest",
        paradigms=["lay"],
        runs=1
    )

    # app.py uses these properties
    assert hasattr(result, 'input_tokens')
    assert hasattr(result, 'output_tokens')
    assert hasattr(result, 'cost_usd')
    assert hasattr(result, 'token_usage')

    # Should NOT have 'total_usage' attribute
    assert not hasattr(result, 'total_usage')

    # Values should be integers/floats
    assert isinstance(result.input_tokens, int)
    assert isinstance(result.output_tokens, int)
    assert isinstance(result.cost_usd, float)

    # token_usage is a method, not a property - must call it
    usage_dict = result.token_usage()
    assert isinstance(usage_dict, dict)
    # Should have per-paradigm entries
    if result.verdicts:
        first_key = list(usage_dict.keys())[0]
        assert first_key in ["lay", "educated_lay", "traditional", "circuit"]


def test_cost_line_signature():
    """Verify cost_line() takes three separate params, not a usage object."""
    # This is how app.py calls it
    cost_text = judging.cost_line(
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.50
    )

    assert isinstance(cost_text, str)
    assert "$" in cost_text
    assert "1,000" in cost_text or "1000" in cost_text
