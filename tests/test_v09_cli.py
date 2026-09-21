from click.testing import CliRunner

from src.cli import cli


def test_new_accepts_aff_and_neg_overrides(tmp_path):
    transcript = tmp_path / "round.txt"
    transcript.write_text(
        "=== 1AC ===\nAff case\n=== CX1 ===\nQuestions\n=== 1NC ===\nNeg case\n"
        "=== CX2 ===\nQuestions\n=== 1AR ===\nAff rebuttal\n=== 2NR ===\nNeg rebuttal\n=== 2AR ===\nAff final\n"
        + ("Additional debate content with warrants and impacts. " * 8),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli,
        [
            "new",
            str(transcript),
            "--dry-run",
            "--yes",
            "--resolution",
            "A sample resolution",
            "--aff",
            "Alice",
            "--neg",
            "Bob",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Alice" in result.output
    assert "Bob" in result.output
    assert "A sample resolution" in result.output


def test_retry_command_is_exposed():
    result = CliRunner().invoke(cli, ["retry", "--help"])
    assert result.exit_code == 0
    assert "--persona" in result.output
    assert "--runs" in result.output
