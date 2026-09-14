"""
Story 7.2 — dry-run mode for prompt inspection.
Story 7.1 — verbose mode for debugging.

Built before the paid work on purpose: these are how the prompts in Increments
7 and 10 get inspected without spending anything.
"""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bedrock_client import (  # noqa: E402
    DRY_RUN_PLACEHOLDER,
    BedrockClient,
    DryRunBedrockClient,
    build_client,
)
from src.cli import cli  # noqa: E402
from src.structure import LabeledSpeech  # noqa: E402
from src.transcript import (  # noqa: E402
    format_round_header,
    format_structured_transcript,
    summarize_speeches,
)

BODY = "Resolved: nuclear weapons are immoral. " + ("transcript filler text " * 30)


@pytest.fixture
def round_folder(tmp_path, monkeypatch) -> Path:
    from src import ingest

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    folder = tmp_path / "New_Rounds" / "LD" / "mark_priya"
    folder.mkdir(parents=True)
    for name in ("1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR"):
        (folder / f"{name}.txt").write_text(BODY, encoding="utf-8")
    return folder


def speech(tmp_path: Path, label: str, speaker: str, position: int, body: str = BODY):
    path = tmp_path / f"{label}.txt"
    path.write_text(body, encoding="utf-8")
    return LabeledSpeech(
        path=path, label=label, speaker=speaker, position=position, source="filename"
    )


# --- Story 7.2: dry-run makes no calls and writes nothing --------------


def test_dry_run_client_never_calls_the_model():
    client = DryRunBedrockClient(echo=False)
    response = client.invoke(system="s", user="u")
    assert response.text == DRY_RUN_PLACEHOLDER


def test_dry_run_reports_zero_tokens_so_cost_stays_honest():
    response = DryRunBedrockClient(echo=False).invoke(system="s", user="u")
    assert (response.input_tokens, response.output_tokens) == (0, 0)
    assert response.cost_usd == 0.0


def test_dry_run_client_records_what_would_have_been_sent():
    client = DryRunBedrockClient(echo=False)
    client.invoke(system="judge as a lay parent", user="the transcript")
    client.invoke(system="judge as circuit", user="the transcript")
    assert client.call_count == 2
    assert client.calls[0]["system"] == "judge as a lay parent"
    assert client.calls[1]["system"] == "judge as circuit"


def test_dry_run_client_needs_no_credentials(monkeypatch):
    def explode(*_a, **_k):
        raise AssertionError("boto3 must never be constructed in dry-run")

    monkeypatch.setattr("src.bedrock_client.boto3.client", explode)
    DryRunBedrockClient(echo=False).invoke(system="s", user="u")


def test_build_client_returns_a_dry_run_client_when_asked():
    assert isinstance(build_client(dry_run=True), DryRunBedrockClient)
    assert isinstance(build_client(dry_run=False), BedrockClient)


def test_dry_run_client_is_not_a_bedrock_subclass():
    """Inheriting risks silently falling through to a real call on refactor."""
    assert not isinstance(DryRunBedrockClient(echo=False), BedrockClient)


def test_cli_dry_run_shows_the_structured_transcript(round_folder):
    result = CliRunner().invoke(cli, ["new", str(round_folder), "--dry-run"], input="\n\n\n")
    assert result.exit_code == 0
    assert "DRY RUN — no model calls, no files written" in result.output
    assert "STRUCTURED TRANSCRIPT" in result.output


def test_cli_dry_run_states_what_it_would_call(round_folder):
    result = CliRunner().invoke(cli, ["new", str(round_folder), "--dry-run"], input="\n\n\n")
    assert "Would call: Lay Parent (RFD cap 80w)." in result.output
    assert "Would call: Technical Circuit (RFD cap 150w)." in result.output
    assert "Would call: cross-paradigm diff." in result.output


def test_cli_dry_run_reports_no_cost(round_folder):
    result = CliRunner().invoke(cli, ["new", str(round_folder), "--dry-run"], input="\n\n\n")
    assert "No cost incurred." in result.output


def test_cli_dry_run_writes_no_files(round_folder, tmp_path):
    before = {p for p in tmp_path.rglob("*")}
    CliRunner().invoke(cli, ["new", str(round_folder), "--dry-run"], input="\n\n\n")
    assert {p for p in tmp_path.rglob("*")} == before


def test_cli_dry_run_leaves_the_inbox_untouched(round_folder):
    CliRunner().invoke(cli, ["new", str(round_folder), "--dry-run"], input="\n\n\n")
    assert len(list(round_folder.iterdir())) == 7


def test_cli_dry_run_elides_long_transcripts_by_default(round_folder):
    result = CliRunner().invoke(cli, ["new", str(round_folder), "--dry-run"], input="\n\n\n")
    assert "more chars — pass --verbose for the full text" in result.output


def test_cli_dry_run_with_verbose_shows_everything(round_folder):
    result = CliRunner().invoke(
        cli, ["new", str(round_folder), "--dry-run", "--verbose"], input="\n\n\n"
    )
    assert "pass --verbose for the full text" not in result.output
    assert result.output.count("=== 2AR") >= 1  # the last speech is present


# --- Story 7.1: verbose goes to stderr, not stdout --------------------


def test_verbose_client_echoes_prompts_and_response(capsys):
    from tests.conftest import FakeBedrockClient  # noqa: F401  (import check)

    class StubBoto:
        def converse(self, **_kwargs):
            return {
                "output": {"message": {"content": [{"text": "WINNER: AFF"}]}},
                "usage": {"inputTokens": 10, "outputTokens": 5},
            }

    client = BedrockClient(verbose=True)
    client._client = StubBoto()
    client.invoke(system="you are a lay parent", user="the transcript")

    captured = capsys.readouterr()
    assert "you are a lay parent" in captured.err
    assert "the transcript" in captured.err
    assert "WINNER: AFF" in captured.err


def test_verbose_output_never_lands_on_stdout(capsys):
    class StubBoto:
        def converse(self, **_kwargs):
            return {
                "output": {"message": {"content": [{"text": "WINNER: AFF"}]}},
                "usage": {"inputTokens": 10, "outputTokens": 5},
            }

    client = BedrockClient(verbose=True)
    client._client = StubBoto()
    client.invoke(system="system text", user="user text")

    captured = capsys.readouterr()
    assert captured.out == ""  # stdout stays clean enough to pipe


def test_non_verbose_client_prints_nothing(capsys):
    class StubBoto:
        def converse(self, **_kwargs):
            return {
                "output": {"message": {"content": [{"text": "ballot"}]}},
                "usage": {"inputTokens": 1, "outputTokens": 1},
            }

    client = BedrockClient(verbose=False)
    client._client = StubBoto()
    client.invoke(system="s", user="u")

    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_verbose_labels_the_call_with_the_model_id(capsys):
    class StubBoto:
        def converse(self, **_kwargs):
            return {
                "output": {"message": {"content": [{"text": "x"}]}},
                "usage": {"inputTokens": 1, "outputTokens": 1},
            }

    client = BedrockClient(verbose=True)
    client._client = StubBoto()
    client.invoke(system="s", user="u")
    assert client.model_id in capsys.readouterr().err


# --- Transcript assembly (prerequisite for 7.2) ----------------------


def test_transcript_marks_every_speech_boundary(tmp_path):
    speeches = [
        speech(tmp_path, "1AC", "Aff", 1),
        speech(tmp_path, "CX1", "Both", 2),
    ]
    text = format_structured_transcript(speeches)
    assert "=== 1AC (Aff," in text
    assert "=== CX1 (Both," in text


def test_transcript_keeps_speeches_in_order(tmp_path):
    speeches = [
        speech(tmp_path, "1AC", "Aff", 1),
        speech(tmp_path, "1NC", "Neg", 3),
        speech(tmp_path, "2AR", "Aff", 7),
    ]
    text = format_structured_transcript(speeches)
    assert text.index("=== 1AC") < text.index("=== 1NC") < text.index("=== 2AR")


def test_transcript_header_names_resolution_and_speakers(tmp_path):
    text = format_structured_transcript(
        [speech(tmp_path, "1AC", "Aff", 1)],
        resolution="Nukes are immoral",
        aff="Eliana",
        neg="Marcus",
    )
    assert 'Resolution: "Nukes are immoral"' in text
    assert "Aff: Eliana | Neg: Marcus" in text


def test_transcript_header_falls_back_to_generic_labels():
    header = format_round_header()
    assert "Resolution: (not provided)" in header
    assert "Aff: Aff | Neg: Neg" in header


def test_unlabeled_segments_still_get_a_boundary(tmp_path):
    path = tmp_path / "speech_01.txt"
    path.write_text(BODY, encoding="utf-8")
    text = format_structured_transcript([LabeledSpeech(path=path)])
    assert "=== Speech 1 (Unknown," in text


def test_transcript_includes_the_speech_text(tmp_path):
    text = format_structured_transcript([speech(tmp_path, "1AC", "Aff", 1)])
    assert "Resolved: nuclear weapons are immoral." in text


def test_word_counts_appear_in_headers(tmp_path):
    speeches = [speech(tmp_path, "1AC", "Aff", 1, body="one two three")]
    assert "=== 1AC (Aff, 3 words) ===" in format_structured_transcript(speeches)


def test_summary_rows_carry_what_the_preview_needs(tmp_path):
    rows = summarize_speeches([speech(tmp_path, "1AC", "Aff", 1, body="a b c")])
    assert rows[0] == {
        "index": 1,
        "label": "1AC",
        "speaker": "Aff",
        "words": 3,
        "source": "filename",
        "file": "1AC.txt",
    }
