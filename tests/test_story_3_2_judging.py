"""
Story 3.2 — judge with a subset of paradigms.
Story 6.2 — token usage and cost.
Plus the RFD word-cap check added after the first real ballot ran 207 words
against a 60-word cap.
"""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.judging import (  # noqa: E402
    DEFAULT_RUNS,
    LABEL_CLEAR,
    LABEL_SLIGHT,
    LABEL_TOSSUP,
    Ballot,
    JudgingResult,
    ParadigmVerdict,
    derive_label,
    extract_winner,
    RfdNotFound,
    cap_violation,
    cost_line,
    extract_rfd,
    judge_round,
    rfd_word_count,
)
from tests.conftest import FakeBedrockClient  # noqa: E402

BALLOT = """WINNER: AFF
LEAN: clear
RFD: The affirmative won on the dropped accident impact.
SPEAKER POINTS: Aff 28 / Neg 27
KEY VOTING ISSUES:
1. The Randall '22 warrant.
"""


def ballot_for(winner: str) -> str:
    return BALLOT.replace("WINNER: AFF", f"WINNER: {winner}")


def make_ballot(winner: str) -> Ballot:
    ballot = Ballot(paradigm="circuit")
    ballot.text = ballot_for(winner)
    return ballot


def ballot_with_rfd(words: int, label: str = "RFD:") -> str:
    return (
        f"WINNER: AFF\nLEAN: clear\n{label} {'word ' * words}\n"
        f"SPEAKER POINTS: Aff 28 / Neg 27\nKEY VOTING ISSUES:\n1. Something.\n"
    )


# --- Story 3.2: only the requested paradigms are called ---------------


def test_one_paradigm_at_runs_one_makes_one_call():
    client = FakeBedrockClient(responses=[BALLOT])
    result = judge_round(client, "transcript", ["lay"], runs=1)
    assert client.call_count == 1
    assert [v.paradigm for v in result.verdicts] == ["lay"]


def test_the_default_is_three_runs_per_paradigm():
    """Story 4.2: the lean label is derived from the split, so N>1 is the norm."""
    assert DEFAULT_RUNS == 3
    client = FakeBedrockClient(responses=[BALLOT])
    judge_round(client, "transcript", ["lay"])
    assert client.call_count == 3


def test_every_run_of_a_paradigm_gets_an_identical_prompt():
    """Variation must come from sampling, not from a changing prompt."""
    client = FakeBedrockClient(responses=[BALLOT])
    judge_round(client, "transcript", ["lay"], runs=3)
    assert len({c["system"] for c in client.calls}) == 1
    assert len({c["user"] for c in client.calls}) == 1


def test_a_subset_calls_only_those_paradigms():
    client = FakeBedrockClient(responses=[BALLOT])
    result = judge_round(client, "transcript", ["lay", "circuit"], runs=2)
    assert client.call_count == 4  # 2 paradigms x 2 runs
    assert [v.paradigm for v in result.verdicts] == ["lay", "circuit"]


def test_each_paradigm_gets_its_own_system_prompt():
    client = FakeBedrockClient(responses=[BALLOT])
    judge_round(client, "transcript", ["lay", "circuit"], runs=1)
    assert "Lay Parent" in client.calls[0]["system"]
    assert "Technical Circuit" in client.calls[1]["system"]
    assert client.calls[0]["system"] != client.calls[1]["system"]


def test_the_transcript_is_the_user_prompt():
    client = FakeBedrockClient(responses=[BALLOT])
    judge_round(client, "the structured transcript", ["lay"], runs=1)
    assert client.calls[0]["user"] == "the structured transcript"


def test_ballots_are_saved_as_they_arrive(store):
    """A crash on paradigm 4 must not lose paradigms 1-3."""
    client = FakeBedrockClient(responses=[BALLOT])
    judge_round(client, "t", ["lay", "circuit"], store=store, round_id="r1", runs=1)
    assert store.personas_for("r1") == ["circuit", "lay"]


def test_saved_ballot_is_the_representative_plus_provenance(store):
    """The file records how the decision was reached, not just the text."""
    client = FakeBedrockClient(responses=[BALLOT])
    judge_round(client, "t", ["lay"], store=store, round_id="r1", runs=3)
    saved = store.load_ballot("r1", "lay")
    assert BALLOT.strip() in saved
    assert "<!-- JudgeAI: Lay Parent · AFF 3/3 · clear · 3 run(s) -->" in saved


def test_the_representative_comes_from_the_majority_side(store):
    client = FakeBedrockClient(
        responses=[ballot_for("NEG"), ballot_for("AFF"), ballot_for("AFF")]
    )
    judge_round(client, "t", ["lay"], store=store, round_id="r1", runs=3)
    assert "WINNER: AFF" in store.load_ballot("r1", "lay")


# --- Story 3.1: a failed paradigm doesn't sink the run ----------------


def test_a_paradigm_whose_every_run_fails_is_recorded_and_the_rest_continue():
    client = FakeBedrockClient(responses=[BALLOT], fail_times=2)
    result = judge_round(client, "t", ["lay", "circuit"], runs=2)
    assert result.failures[0].paradigm == "lay"
    assert result.successful[0].paradigm == "circuit"


def test_one_failed_run_does_not_fail_the_paradigm():
    """Two good runs out of three still yield a decision."""
    client = FakeBedrockClient(responses=[BALLOT], fail_times=1)
    result = judge_round(client, "t", ["lay"], runs=3)
    verdict = result.verdicts[0]
    assert verdict.ok
    assert verdict.vote_share == "2/2"


def test_a_failure_keeps_its_error_message():
    client = FakeBedrockClient(
        responses=[BALLOT], fail_times=3, exception=RuntimeError("rate limited")
    )
    result = judge_round(client, "t", ["lay"], runs=3)
    assert "rate limited" in result.failures[0].usage()["errors"][0]


def test_failed_paradigms_contribute_no_cost():
    client = FakeBedrockClient(responses=[BALLOT], fail_times=1)
    result = judge_round(client, "t", ["lay"], runs=1)
    assert result.cost_usd == 0.0


# --- Story 6.2: usage and cost ---------------------------------------


def test_totals_sum_across_paradigms_and_runs():
    client = FakeBedrockClient(responses=[BALLOT])
    result = judge_round(client, "t", ["lay", "circuit"], runs=3)
    assert result.input_tokens == 6000   # 2 paradigms x 3 runs x 1000
    assert result.output_tokens == 1200


def test_the_flow_pass_is_counted_once_not_per_run():
    """It is computed upstream and shared, which is why N runs stay affordable."""
    result = JudgingResult(flow_input_tokens=10_000, flow_output_tokens=1_700)
    assert result.input_tokens == 10_000
    assert result.output_tokens == 1_700


def test_token_usage_is_recorded_per_paradigm():
    client = FakeBedrockClient(responses=[BALLOT])
    usage = judge_round(client, "t", ["lay", "circuit"], runs=3).token_usage()
    assert set(usage) == {"lay", "circuit"}
    assert usage["lay"]["input_tokens"] == 3000
    assert usage["lay"]["runs"] == 3
    assert usage["lay"]["failed"] is False


def test_usage_records_the_vote_and_the_label():
    client = FakeBedrockClient(
        responses=[ballot_for("AFF"), ballot_for("AFF"), ballot_for("NEG")]
    )
    usage = judge_round(client, "t", ["lay"], runs=3).token_usage()["lay"]
    assert usage["winner"] == "AFF"
    assert usage["vote_share"] == "2/3"
    assert usage["label"] == LABEL_SLIGHT
    assert usage["run_winners"] == ["AFF", "AFF", "NEG"]


def test_failed_paradigm_usage_carries_the_error():
    client = FakeBedrockClient(responses=[BALLOT], fail_times=1)
    usage = judge_round(client, "t", ["lay"], runs=1).token_usage()
    assert usage["lay"]["failed"] is True
    assert "errors" in usage["lay"]


def test_cost_line_matches_the_acceptance_criteria():
    assert cost_line(41238, 9127, 0.26) == (
        "Total: 41,238 input + 9,127 output tokens ≈ $0.26"
    )


def test_empty_result_totals_are_zero():
    assert JudgingResult().cost_usd == 0.0


# --- Story 4.2: labels derived from the split, not self-reported ------


def test_unanimous_runs_are_clear():
    assert derive_label(["AFF", "AFF", "AFF"], [None, None, None]) == LABEL_CLEAR


def test_a_split_is_a_slight_lean():
    assert derive_label(["AFF", "AFF", "NEG"], [None, None, None]) == LABEL_SLIGHT


def test_a_majority_self_reported_tossup_is_honoured():
    """An odd-N vote share can never produce a tie, so toss-up needs this route."""
    assert derive_label(
        ["AFF", "AFF", "NEG"], ["toss-up", "toss-up", "clear"]
    ) == LABEL_TOSSUP


def test_an_even_split_is_a_tossup():
    assert derive_label(["AFF", "NEG"], [None, None]) == LABEL_TOSSUP


def test_no_parseable_winner_is_a_tossup():
    assert derive_label([], []) == LABEL_TOSSUP


def test_strong_lean_is_no_longer_produced():
    """Removed 2026-08-16: N=3 gives 1/3 resolution, supporting two bands."""
    labels = {
        derive_label(w, [None] * len(w))
        for w in (["AFF"], ["AFF", "AFF"], ["AFF", "AFF", "NEG"], ["AFF"] * 3)
    }
    assert "strong lean" not in labels


@pytest.mark.parametrize("winners,expected", [
    (["AFF", "AFF", "AFF"], "AFF (3/3) clear"),
    (["AFF", "AFF", "NEG"], "AFF (2/3) slight lean"),
    (["NEG", "NEG", "AFF"], "NEG (2/3) slight lean"),
])
def test_decision_line_shows_winner_share_and_label(winners, expected):
    verdict = ParadigmVerdict("circuit", [make_ballot(w) for w in winners])
    assert verdict.decision == expected


def test_a_fully_failed_paradigm_reports_no_ballot():
    failed = Ballot(paradigm="lay", failed=True, error="boom")
    assert ParadigmVerdict("lay", [failed]).decision == "FAILED — no ballot"


def test_extract_winner_tolerates_markdown():
    for text in ("WINNER: AFF", "**WINNER:** AFF", "## WINNER: AFF", "# WINNER AFF"):
        assert extract_winner(text) == "AFF"


# --- RFD word caps ---------------------------------------------------


def test_rfd_is_extracted_from_a_plain_label():
    assert extract_rfd(BALLOT) == "The affirmative won on the dropped accident impact."


@pytest.mark.parametrize("label", ["RFD:", "**RFD:**", "## RFD:", "### RFD", "**RFD**"])
def test_rfd_is_extracted_from_every_format_the_model_uses(label):
    """The first real run used "## RFD:" and an earlier pattern matched nothing."""
    assert rfd_word_count(ballot_with_rfd(10, label)) == 10


def test_an_unparseable_ballot_raises_rather_than_counting_zero():
    """A parse failure that reads as "within cap" is worse than no check."""
    with pytest.raises(RfdNotFound):
        rfd_word_count("WINNER: AFF\nno rfd block here at all\n")


def test_unparseable_ballot_is_reported_as_a_violation():
    message = cap_violation("lay", "WINNER: AFF\nnothing parseable\n")
    assert "format unrecognized" in message


def test_an_rfd_within_cap_produces_no_warning():
    assert cap_violation("lay", ballot_with_rfd(50)) is None


def test_an_rfd_at_the_cap_is_allowed():
    assert cap_violation("lay", ballot_with_rfd(80)) is None


def test_an_over_cap_rfd_is_reported_with_both_numbers():
    message = cap_violation("lay", ballot_with_rfd(307))
    assert message == "Lay Parent RFD is 307 words, cap is 80."


def test_caps_differ_by_paradigm():
    """120 words passes for Circuit and fails for Lay — the paradigms differ."""
    one_twenty = ballot_with_rfd(120)
    assert cap_violation("circuit", one_twenty) is None
    assert cap_violation("lay", one_twenty) is not None


# --- CLI integration -------------------------------------------------


@pytest.fixture
def labeled_round(tmp_path, monkeypatch):
    from src import ingest, storage

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    monkeypatch.setattr(storage, "DEFAULT_BALLOTS_ROOT", tmp_path / "Ballots")
    folder = tmp_path / "New_Rounds" / "LD" / "mark_priya"
    folder.mkdir(parents=True)
    for name in ("1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR"):
        (folder / f"{name}.txt").write_text("word " * 60, encoding="utf-8")
    return folder, tmp_path / "Ballots"


def test_cli_rejects_an_unknown_persona(labeled_round):
    folder, _ballots = labeled_round
    result = CliRunner().invoke(cli_app(), ["new", str(folder), "--personas", "lyd"])
    assert "Unknown persona 'lyd'" in result.output
    assert "lay, educated_lay, traditional, circuit, all" in result.output


def cli_app():
    from src.cli import cli

    return cli


def test_cli_single_persona_prints_the_ballot(labeled_round, monkeypatch):
    folder, _ballots = labeled_round
    monkeypatch.setattr(
        "src.cli.build_client", lambda **_kw: FakeBedrockClient(responses=[BALLOT])
    )
    result = CliRunner().invoke(
        cli_app(),
        ["new", str(folder), "--personas", "lay", "--runs", "1"],
        input="\n\n\ny\n",
    )
    assert "WINNER: AFF" in result.output
    assert "Cross-paradigm diff" not in result.output  # nothing to compare


def test_cli_reports_the_cost_line(labeled_round, monkeypatch):
    folder, _ballots = labeled_round
    monkeypatch.setattr(
        "src.cli.build_client", lambda **_kw: FakeBedrockClient(responses=[BALLOT])
    )
    result = CliRunner().invoke(
        cli_app(),
        ["new", str(folder), "--personas", "lay", "--runs", "1"],
        input="\n\n\ny\n",
    )
    assert "Total: 1,000 input + 200 output tokens" in result.output


def test_cli_reports_the_vote_share_per_paradigm(labeled_round, monkeypatch):
    folder, _ballots = labeled_round
    monkeypatch.setattr(
        "src.cli.build_client", lambda **_kw: FakeBedrockClient(responses=[BALLOT])
    )
    result = CliRunner().invoke(
        cli_app(), ["new", str(folder), "--personas", "lay"], input="\n\n\ny\n"
    )
    assert "-> Lay Parent: AFF (3/3) clear" in result.output


def test_cli_warns_when_a_ballot_exceeds_its_cap(labeled_round, monkeypatch):
    folder, _ballots = labeled_round
    monkeypatch.setattr(
        "src.cli.build_client",
        lambda **_kw: FakeBedrockClient(responses=[ballot_with_rfd(307)]),
    )
    result = CliRunner().invoke(
        cli_app(),
        ["new", str(folder), "--personas", "lay", "--runs", "1"],
        input="\n\n\ny\n",
    )
    assert "warning: Lay Parent RFD is 307 words, cap is 80." in result.output


def test_cli_writes_ballot_transcript_and_metadata(labeled_round, monkeypatch):
    folder, ballots_root = labeled_round
    monkeypatch.setattr(
        "src.cli.build_client", lambda **_kw: FakeBedrockClient(responses=[BALLOT])
    )
    CliRunner().invoke(
        cli_app(),
        ["new", str(folder), "--personas", "lay", "--runs", "1"],
        input="\n\n\ny\n",
    )
    round_dir = next(ballots_root.iterdir())
    names = {p.name for p in round_dir.iterdir()}
    # Lay is denied the flow, so no flow.md is written for a lay-only run.
    assert names == {"judge_lay.md", "structured_transcript.md", "metadata.json"}


def test_metadata_records_per_paradigm_usage(labeled_round, monkeypatch):
    import json

    folder, ballots_root = labeled_round
    monkeypatch.setattr(
        "src.cli.build_client", lambda **_kw: FakeBedrockClient(responses=[BALLOT])
    )
    CliRunner().invoke(
        cli_app(), ["new", str(folder), "--personas", "lay"], input="\n\n\ny\n"
    )
    meta = json.loads((next(ballots_root.iterdir()) / "metadata.json").read_text())
    assert meta["token_usage"]["lay"]["output_tokens"] == 600  # 3 runs
    assert meta["paradigms"] == ["lay"]
    assert meta["runs_per_paradigm"] == 3
    assert meta["decisions"]["lay"] == "AFF (3/3) clear"
    assert meta["total_cost_usd"] > 0
