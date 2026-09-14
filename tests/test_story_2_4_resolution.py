"""
Story 2.4 — Auto-detect the resolution from transcript text.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.detection import (  # noqa: E402
    NO_RESOLUTION_MESSAGE,
    ResolutionCandidate,
    confirm_prompt,
    conflict_prompt,
    reconcile_resolutions,
    resolutions_align,
)
from src.metadata import (  # noqa: E402
    SOURCE_DETECTED,
    SOURCE_FLAG,
    SOURCE_YAML,
    confirm_detected_resolution,
    resolve_metadata,
)

NUKES = "The possession of nuclear weapons is immoral."
LIBERTIES = "Democracies ought to prioritize civil liberties over national security."


def candidate(text, label="1AC", confidence="high") -> ResolutionCandidate:
    return ResolutionCandidate(text=text, source_label=label, confidence=confidence)


class Answers:
    """Scripted responses, recording the prompts they answered."""

    def __init__(self, *answers):
        self.queue = list(answers)
        self.prompts = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.queue.pop(0) if self.queue else ""


# --- A clear resolution is confirmed ----------------------------------


def test_detected_resolution_is_offered_for_confirmation():
    answers = Answers("")  # Enter accepts
    assert confirm_detected_resolution([candidate(NUKES)], ask=answers) == NUKES
    assert answers.prompts[0] == f"Detected resolution: '{NUKES}' Use this? [Y/edit/skip]"


def test_confirmation_prompt_wording():
    assert confirm_prompt(candidate(NUKES)) == (
        f"Detected resolution: '{NUKES}' Use this? [Y/edit/skip]"
    )


@pytest.mark.parametrize("answer", ["", "y", "Y", "yes"])
def test_accepting_uses_the_detected_text(answer):
    assert confirm_detected_resolution([candidate(NUKES)], ask=Answers(answer)) == NUKES


def test_edit_lets_the_user_type_a_replacement():
    answers = Answers("edit", "A better phrasing")
    assert confirm_detected_resolution([candidate(NUKES)], ask=answers) == "A better phrasing"


def test_skip_falls_through_to_the_story_1_3_prompt():
    assert confirm_detected_resolution([candidate(NUKES)], ask=Answers("skip")) is None


# --- Aligned candidates across files need no prompt -------------------


def test_punctuation_and_case_differences_still_align():
    assert resolutions_align(NUKES, "the possession of nuclear weapons is immoral")
    assert resolutions_align(NUKES, "Resolved: The possession of nuclear weapons is immoral")


def test_substantively_different_texts_do_not_align():
    assert not resolutions_align(NUKES, LIBERTIES)


def test_aligned_candidates_collapse_to_one():
    agreed, conflicts = reconcile_resolutions([
        candidate(NUKES, "1AC"),
        candidate("resolved: the possession of nuclear weapons is immoral", "2AR"),
    ])
    assert conflicts == []
    assert agreed.text == NUKES


def test_high_confidence_phrasing_wins_among_aligned_candidates():
    agreed, _ = reconcile_resolutions([
        candidate("the possession of nuclear weapons is immoral", "2AR", "medium"),
        candidate(NUKES, "1AC", "high"),
    ])
    assert agreed.confidence == "high"


def test_aligned_candidates_are_only_confirmed_once():
    answers = Answers("")
    confirm_detected_resolution(
        [candidate(NUKES, "1AC"), candidate(NUKES, "2AR")], ask=answers
    )
    assert len(answers.prompts) == 1


# --- Divergent candidates prompt for a choice ------------------------


def test_divergent_candidates_are_reported_as_conflicts():
    agreed, conflicts = reconcile_resolutions([
        candidate(NUKES, "1AC"), candidate(LIBERTIES, "1NC")
    ])
    assert agreed is None
    assert [c.source_label for c in conflicts] == ["1AC", "1NC"]


def test_conflict_prompt_lists_lettered_options():
    prompt = conflict_prompt([candidate(NUKES, "1AC"), candidate(LIBERTIES, "1NC")])
    assert "Detected different resolutions across speech files:" in prompt
    assert f"(a) From 1AC: '{NUKES}'" in prompt
    assert f"(b) From 1NC: '{LIBERTIES}'" in prompt
    assert "Which one is correct? [a/b/edit/skip]" in prompt


def test_choosing_a_selects_the_first_candidate():
    result = confirm_detected_resolution(
        [candidate(NUKES, "1AC"), candidate(LIBERTIES, "1NC")], ask=Answers("a")
    )
    assert result == NUKES


def test_choosing_b_selects_the_second_candidate():
    result = confirm_detected_resolution(
        [candidate(NUKES, "1AC"), candidate(LIBERTIES, "1NC")], ask=Answers("b")
    )
    assert result == LIBERTIES


def test_edit_works_from_the_conflict_prompt():
    answers = Answers("edit", "Neither of those")
    result = confirm_detected_resolution(
        [candidate(NUKES, "1AC"), candidate(LIBERTIES, "1NC")], ask=answers
    )
    assert result == "Neither of those"


def test_skip_from_the_conflict_prompt_falls_through():
    result = confirm_detected_resolution(
        [candidate(NUKES, "1AC"), candidate(LIBERTIES, "1NC")], ask=Answers("skip")
    )
    assert result is None


def test_unrecognized_answer_falls_through_rather_than_guessing():
    result = confirm_detected_resolution(
        [candidate(NUKES, "1AC"), candidate(LIBERTIES, "1NC")], ask=Answers("q")
    )
    assert result is None


def test_three_way_conflict_offers_three_letters():
    prompt = conflict_prompt([
        candidate(NUKES, "1AC"), candidate(LIBERTIES, "1NC"), candidate("A third", "2AR")
    ])
    assert "(c) From 2AR: 'A third'" in prompt
    assert "[a/b/c/edit/skip]" in prompt


# --- Nothing detected -------------------------------------------------


def test_no_candidates_falls_through_without_prompting():
    answers = Answers()
    assert confirm_detected_resolution([], ask=answers) is None
    assert answers.prompts == []


def test_low_confidence_candidates_are_not_offered():
    """A guess isn't worth a prompt; the Story 1.3 prompt handles it."""
    answers = Answers()
    assert confirm_detected_resolution([candidate(NUKES, "1AC", "low")], ask=answers) is None
    assert answers.prompts == []


def test_empty_text_is_ignored():
    assert confirm_detected_resolution([candidate("", "1AC")], ask=Answers()) is None


def test_failure_message_is_available_for_the_cli():
    assert NO_RESOLUTION_MESSAGE == "Could not auto-detect resolution."


# --- Precedence (Story 2.4's ordering, verified end to end) -----------


def test_detected_resolution_is_used_when_nothing_outranks_it():
    meta = resolve_metadata(detected_resolution=NUKES, prompt=lambda _l: "")
    assert meta.resolution == NUKES
    assert meta.sources["resolution"] == SOURCE_DETECTED


def test_flag_outranks_detection_and_the_loser_is_logged():
    meta = resolve_metadata(
        cli_resolution=LIBERTIES, detected_resolution=NUKES, prompt=lambda _l: ""
    )
    assert meta.resolution == LIBERTIES
    assert meta.sources["resolution"] == SOURCE_FLAG
    assert meta.overridden_detection == NUKES


def test_yaml_outranks_everything():
    meta = resolve_metadata(
        yaml_metadata={"resolution": "from yaml"},
        cli_resolution=LIBERTIES,
        detected_resolution=NUKES,
        prompt=lambda _l: "",
    )
    assert meta.resolution == "from yaml"
    assert meta.sources["resolution"] == SOURCE_YAML
    assert meta.overridden_detection == NUKES


# --- CLI reporting distinguishes where labels came from ---------------


def test_model_detected_speeches_are_not_reported_as_unlabeled(tmp_path, monkeypatch):
    """First real run mislabeled detected speeches as "unlabeled"."""
    import json

    from click.testing import CliRunner

    from src import ingest
    from src.cli import cli
    from tests.conftest import FakeBedrockClient

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    path = tmp_path / "round.txt"
    path.write_text(
        "My name is Drew and I affirm. " + ("filler text " * 60), encoding="utf-8"
    )

    payload = json.dumps({
        "speeches": [{"label": "1AC", "speaker": "Aff",
                      "start_marker": "My name is Drew and I affirm"}],
        "resolution": {"text": NUKES, "quote": "x", "confidence": "high"},
        "notes": "",
    })
    monkeypatch.setattr(
        "src.cli.build_client",
        lambda **_kw: FakeBedrockClient(responses=[payload]),
    )

    result = CliRunner().invoke(cli, ["new", str(path)], input="y\n\n\n")
    assert "[detected: 1AC" in result.output
    assert "unlabeled: 1AC" not in result.output
    assert "no detection call needed" not in result.output
    assert "Structure detected from the transcript." in result.output


def test_detected_resolution_is_reported_as_its_source(tmp_path, monkeypatch):
    import json

    from click.testing import CliRunner

    from src import ingest
    from src.cli import cli
    from tests.conftest import FakeBedrockClient

    monkeypatch.setattr(ingest, "INBOX_ROOT", tmp_path / "New_Rounds")
    path = tmp_path / "round.txt"
    path.write_text("My name is Drew. " + ("filler text " * 60), encoding="utf-8")

    payload = json.dumps({
        "speeches": [{"label": "1AC", "speaker": "Aff", "start_marker": "My name is Drew"}],
        "resolution": {"text": NUKES, "quote": "x", "confidence": "high"},
        "notes": "",
    })
    monkeypatch.setattr(
        "src.cli.build_client",
        lambda **_kw: FakeBedrockClient(responses=[payload]),
    )

    result = CliRunner().invoke(cli, ["new", str(path)], input="y\n\n\n")
    assert f'Resolution: "{NUKES}" (auto-detected)' in result.output
