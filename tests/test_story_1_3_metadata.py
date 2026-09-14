"""
Story 1.3 — Provide optional round metadata.

Precedence under test: round.yaml > --resolution flag > auto-detected >
interactive prompt. Prompts are injected, so nothing blocks on stdin.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest import IngestError, metadata_file_in  # noqa: E402
from src.metadata import (  # noqa: E402
    SOURCE_DETECTED,
    SOURCE_FLAG,
    SOURCE_PROMPT,
    SOURCE_SKIPPED,
    SOURCE_YAML,
    RoundMetadata,
    load_metadata_file,
    resolve_metadata,
)

NUCLEAR = "The possession of nuclear weapons is immoral."


class RecordingPrompt:
    """Records which fields were asked for, and answers from a script."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.asked = []

    def __call__(self, label: str) -> str:
        self.asked.append(label)
        return self.answers.get(label, "")


def never_prompt(label: str) -> str:
    raise AssertionError(f"must not prompt for {label!r}")


def write_yaml(tmp_path: Path, body: str, name: str = "round.yaml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# --- Given no metadata anywhere, prompts appear in order ----------------


def test_all_three_fields_are_prompted_one_at_a_time():
    prompt = RecordingPrompt()
    resolve_metadata(prompt=prompt)
    assert prompt.asked == ["Resolution", "Aff speaker name", "Neg speaker name"]


def test_prompted_answers_are_used():
    prompt = RecordingPrompt(
        {"Resolution": NUCLEAR, "Aff speaker name": "Eliana", "Neg speaker name": "Marcus"}
    )
    meta = resolve_metadata(prompt=prompt)
    assert (meta.resolution, meta.aff, meta.neg) == (NUCLEAR, "Eliana", "Marcus")
    assert meta.sources == {
        "resolution": SOURCE_PROMPT,
        "aff": SOURCE_PROMPT,
        "neg": SOURCE_PROMPT,
    }


# --- Given Enter at a prompt, the field is skipped ---------------------


def test_pressing_enter_skips_every_field():
    meta = resolve_metadata(prompt=lambda _label: "")
    assert (meta.resolution, meta.aff, meta.neg) == (None, None, None)
    assert set(meta.sources.values()) == {SOURCE_SKIPPED}


def test_skipped_speakers_fall_back_to_generic_labels():
    meta = resolve_metadata(prompt=lambda _label: "")
    assert (meta.aff_label, meta.neg_label) == ("Aff", "Neg")


def test_skipped_resolution_means_no_resolution_is_quoted():
    meta = resolve_metadata(prompt=lambda _label: "")
    assert meta.has_resolution is False


def test_whitespace_only_answer_counts_as_skipped():
    meta = resolve_metadata(prompt=lambda _label: "   ")
    assert meta.aff is None


def test_partial_answers_are_kept_and_the_rest_skipped():
    prompt = RecordingPrompt({"Aff speaker name": "Eliana"})
    meta = resolve_metadata(prompt=prompt)
    assert meta.aff == "Eliana"
    assert meta.neg is None and meta.neg_label == "Neg"


# --- Given a complete round.yaml, nothing is prompted -----------------


def test_complete_yaml_suppresses_all_prompts(tmp_path):
    path = write_yaml(
        tmp_path,
        f'resolution: "{NUCLEAR}"\naff: "Eliana"\nneg: "Marcus"\n',
    )
    meta = resolve_metadata(load_metadata_file(path), prompt=never_prompt)
    assert (meta.resolution, meta.aff, meta.neg) == (NUCLEAR, "Eliana", "Marcus")
    assert set(meta.sources.values()) == {SOURCE_YAML}


def test_yaml_beats_the_resolution_flag(tmp_path):
    path = write_yaml(tmp_path, 'resolution: "from yaml"\naff: "E"\nneg: "M"\n')
    meta = resolve_metadata(
        load_metadata_file(path), cli_resolution="from flag", prompt=never_prompt
    )
    assert meta.resolution == "from yaml"


def test_yaml_beats_auto_detection(tmp_path):
    path = write_yaml(tmp_path, 'resolution: "from yaml"\naff: "E"\nneg: "M"\n')
    meta = resolve_metadata(
        load_metadata_file(path), detected_resolution="from model", prompt=never_prompt
    )
    assert meta.resolution == "from yaml"


def test_overridden_detection_is_recorded_not_discarded(tmp_path):
    """Story 2.4: a losing auto-detected value is still logged for reference."""
    path = write_yaml(tmp_path, 'resolution: "from yaml"\naff: "E"\nneg: "M"\n')
    meta = resolve_metadata(
        load_metadata_file(path), detected_resolution="from model", prompt=never_prompt
    )
    assert meta.overridden_detection == "from model"
    assert meta.to_dict()["overridden_detection"] == "from model"


# --- Given a partial round.yaml, only missing fields are prompted -----


def test_resolution_only_yaml_prompts_for_the_two_speakers(tmp_path):
    path = write_yaml(tmp_path, f'resolution: "{NUCLEAR}"\n')
    prompt = RecordingPrompt({"Aff speaker name": "Eliana"})
    meta = resolve_metadata(load_metadata_file(path), prompt=prompt)
    assert prompt.asked == ["Aff speaker name", "Neg speaker name"]
    assert meta.sources["resolution"] == SOURCE_YAML
    assert meta.sources["aff"] == SOURCE_PROMPT


def test_speakers_only_yaml_prompts_for_the_resolution(tmp_path):
    path = write_yaml(tmp_path, 'aff: "Eliana"\nneg: "Marcus"\n')
    prompt = RecordingPrompt({"Resolution": NUCLEAR})
    meta = resolve_metadata(load_metadata_file(path), prompt=prompt)
    assert prompt.asked == ["Resolution"]
    assert meta.resolution == NUCLEAR


def test_blank_yaml_value_is_treated_as_missing(tmp_path):
    path = write_yaml(tmp_path, 'resolution: ""\naff: "Eliana"\nneg: "Marcus"\n')
    prompt = RecordingPrompt({"Resolution": NUCLEAR})
    resolve_metadata(load_metadata_file(path), prompt=prompt)
    assert prompt.asked == ["Resolution"]


# --- The --resolution flag --------------------------------------------


def test_flag_is_used_when_there_is_no_yaml():
    meta = resolve_metadata(cli_resolution=NUCLEAR, prompt=lambda _l: "")
    assert meta.resolution == NUCLEAR
    assert meta.sources["resolution"] == SOURCE_FLAG


def test_flag_beats_auto_detection():
    meta = resolve_metadata(
        cli_resolution="from flag", detected_resolution="from model", prompt=lambda _l: ""
    )
    assert meta.resolution == "from flag"
    assert meta.overridden_detection == "from model"


def test_flag_suppresses_only_the_resolution_prompt():
    prompt = RecordingPrompt()
    resolve_metadata(cli_resolution=NUCLEAR, prompt=prompt)
    assert prompt.asked == ["Aff speaker name", "Neg speaker name"]


# --- Auto-detected resolution (the slot Story 2.4 fills) --------------


def test_detected_resolution_is_used_when_nothing_outranks_it():
    meta = resolve_metadata(detected_resolution=NUCLEAR, prompt=lambda _l: "")
    assert meta.resolution == NUCLEAR
    assert meta.sources["resolution"] == SOURCE_DETECTED


def test_detected_resolution_suppresses_the_resolution_prompt():
    prompt = RecordingPrompt()
    resolve_metadata(detected_resolution=NUCLEAR, prompt=prompt)
    assert "Resolution" not in prompt.asked


# --- Reading the yaml file -------------------------------------------


def test_yaml_keys_are_matched_case_insensitively(tmp_path):
    path = write_yaml(tmp_path, f'Resolution: "{NUCLEAR}"\nAFF: "Eliana"\n')
    loaded = load_metadata_file(path)
    assert loaded["resolution"] == NUCLEAR and loaded["aff"] == "Eliana"


def test_unknown_yaml_keys_are_ignored(tmp_path):
    path = write_yaml(tmp_path, 'aff: "Eliana"\ntournament: "State finals"\n')
    assert load_metadata_file(path) == {"aff": "Eliana"}


def test_empty_yaml_file_means_no_metadata(tmp_path):
    assert load_metadata_file(write_yaml(tmp_path, "")) == {}


def test_malformed_yaml_raises_rather_than_being_ignored(tmp_path):
    """
    A typo'd sidecar must not be silently skipped — the user would believe
    their resolution was used when it wasn't.
    """
    path = write_yaml(tmp_path, 'resolution: "unclosed\naff: [1, 2\n')
    with pytest.raises(IngestError) as caught:
        load_metadata_file(path)
    assert "Could not parse round.yaml" in str(caught.value)


def test_yaml_that_is_not_a_mapping_raises(tmp_path):
    path = write_yaml(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(IngestError) as caught:
        load_metadata_file(path)
    assert "must be a mapping" in str(caught.value)


def test_non_string_scalars_are_coerced(tmp_path):
    """A speaker name that looks like a number must not break."""
    path = write_yaml(tmp_path, "aff: 42\n")
    assert load_metadata_file(path) == {"aff": "42"}


def test_yml_extension_is_accepted(tmp_path):
    (tmp_path / "1AC.txt").write_text("x")
    write_yaml(tmp_path, 'aff: "Eliana"\n', name="round.yml")
    found = metadata_file_in(tmp_path)
    assert found is not None and found.suffix == ".yml"


# --- Sidecar discovery ------------------------------------------------


def test_sidecar_named_after_the_transcript_wins(tmp_path):
    """
    A loose .txt in the inbox must not adopt a neighbouring round's yaml.
    """
    (tmp_path / "nuclear_weapons.txt").write_text("x")
    write_yaml(tmp_path, 'aff: "Neighbour"\n', name="round.yaml")
    write_yaml(tmp_path, 'aff: "Correct"\n', name="nuclear_weapons.yaml")
    found = metadata_file_in(tmp_path, stem="nuclear_weapons")
    assert load_metadata_file(found) == {"aff": "Correct"}


def test_round_yaml_is_the_fallback_when_no_named_sidecar_exists(tmp_path):
    (tmp_path / "1AC.txt").write_text("x")
    write_yaml(tmp_path, 'aff: "Eliana"\n', name="round.yaml")
    found = metadata_file_in(tmp_path, stem="1AC")
    assert found.name == "round.yaml"


def test_no_sidecar_returns_none(tmp_path):
    (tmp_path / "1AC.txt").write_text("x")
    assert metadata_file_in(tmp_path) is None


# --- Serialization ----------------------------------------------------


def test_to_dict_carries_fields_and_provenance():
    meta = RoundMetadata(
        resolution=NUCLEAR, aff="Eliana", sources={"resolution": SOURCE_YAML}
    )
    payload = meta.to_dict()
    assert payload["resolution"] == NUCLEAR
    assert payload["aff"] == "Eliana"
    assert payload["neg"] is None
    assert payload["metadata_sources"] == {"resolution": SOURCE_YAML}


def test_to_dict_omits_overridden_detection_when_absent():
    assert "overridden_detection" not in RoundMetadata().to_dict()


# --- End-to-end through the CLI --------------------------------------


def test_cli_reads_a_round_yaml_without_prompting(tmp_path):
    from click.testing import CliRunner

    from src.cli import cli

    folder = tmp_path / "mark_priya"
    folder.mkdir()
    body = "Resolved: " + NUCLEAR + " " + ("filler text " * 40)
    for name in ("1AC", "CX1", "1NC", "CX2", "1AR"):
        (folder / f"{name}.txt").write_text(body, encoding="utf-8")
    write_yaml(folder, f'resolution: "{NUCLEAR}"\naff: "Eliana"\nneg: "Marcus"\n')

    result = CliRunner().invoke(cli, ["new", str(folder)], input="")
    assert result.exit_code == 0
    assert f'Resolution: "{NUCLEAR}" (round.yaml)' in result.output
    assert "Aff: Eliana (round.yaml)" in result.output
    assert "Neg: Marcus (round.yaml)" in result.output


def test_cli_falls_back_to_generic_labels_with_no_metadata(tmp_path):
    from click.testing import CliRunner

    from src.cli import cli

    path = tmp_path / "round.txt"
    path.write_text("Resolved: something. " + ("filler text " * 40), encoding="utf-8")

    result = CliRunner().invoke(cli, ["new", str(path)], input="\n\n\n")
    assert "Aff: Aff (generic label)" in result.output
    assert "Neg: Neg (generic label)" in result.output


def test_cli_resolution_flag_is_reported_as_its_source(tmp_path):
    from click.testing import CliRunner

    from src.cli import cli

    path = tmp_path / "round.txt"
    path.write_text("filler text " * 40, encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["new", str(path), "--resolution", NUCLEAR], input="\n\n"
    )
    assert f'Resolution: "{NUCLEAR}" (--resolution flag)' in result.output


def test_cli_reports_malformed_yaml_as_a_clean_error(tmp_path):
    from click.testing import CliRunner

    from src.cli import cli

    folder = tmp_path / "mark_priya"
    folder.mkdir()
    for name in ("1AC", "CX1", "1NC", "CX2", "1AR"):
        (folder / f"{name}.txt").write_text("filler text " * 40, encoding="utf-8")
    write_yaml(folder, 'resolution: "unclosed\naff: [1, 2\n')

    result = CliRunner().invoke(cli, ["new", str(folder)], input="")
    assert "Could not parse round.yaml" in result.output
    assert "Traceback" not in result.output
