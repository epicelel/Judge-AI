from pathlib import Path

from src.gui_services import (
    classify_run_error,
    combined_report,
    detect_resolution_locally,
    estimate_cost_usd,
    preflight_transcript,
)


def test_preflight_detects_explicit_metadata_without_model(tmp_path: Path):
    transcript = tmp_path / "round.txt"
    transcript.write_text(
        'Resolution: Protecting the environment is more important than economic growth.\n'
        'Aff: Eliana Chen | Neg: Marcus Lee\n\n=== 1AC ===\nHello.\n',
        encoding="utf-8",
    )
    info = preflight_transcript(transcript)
    assert info.debate_format == "LD"
    assert info.resolution.startswith("Protecting the environment")
    assert info.aff == "Eliana Chen"
    assert info.neg == "Marcus Lee"
    assert info.chars > 20


def test_resolution_detector_does_not_guess_unlabelled_prose():
    assert detect_resolution_locally("We should protect the environment for many reasons.") is None


def test_cost_estimate_grows_with_runs_and_paradigms():
    low1, high1 = estimate_cost_usd(40000, ["lay"], 1, "OpenAI", "gpt-5.6-luna")
    low3, high3 = estimate_cost_usd(
        40000, ["lay", "educated_lay", "traditional", "circuit"], 3, "OpenAI", "gpt-5.6-luna"
    )
    assert 0 <= low1 <= high1
    assert low3 > low1
    assert high3 > high1


def test_combined_report_contains_diff_and_ballots():
    report = combined_report(
        "123456.010126.topic.aff",
        {"date": "2026-01-01", "resolution": "R", "aff": "A", "neg": "N"},
        "DIFF",
        {"Lay Parent": "BALLOT"},
    )
    assert "# JudgeAI Round Report" in report
    assert "DIFF" in report
    assert "## Lay Parent" in report
    assert "BALLOT" in report


def test_rate_limit_error_gets_friendly_message():
    title, body = classify_run_error("OpenAI 429 rate limit exceeded")
    assert "Rate limit" in title
    assert "retry" in body.lower()
