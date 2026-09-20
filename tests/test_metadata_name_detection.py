from pathlib import Path

from src.metadata import (
    SOURCE_TRANSCRIPT,
    detect_participant_names,
    resolve_metadata,
)
from src.structure import LabeledSpeech


def _speech(path: Path, label: str, position: int):
    return LabeledSpeech(path=path, label=label, speaker="Aff" if "A" in label else "Neg", position=position)


def test_detects_combined_aff_neg_header(tmp_path):
    path = tmp_path / "round.txt"
    path.write_text("Aff: Eliana Chen | Neg: Marcus Lee\nResolved: test", encoding="utf-8")
    found = detect_participant_names([path])
    assert found == {"aff": "Eliana Chen", "neg": "Marcus Lee"}


def test_ignores_generic_aff_neg_header(tmp_path):
    path = tmp_path / "round.txt"
    path.write_text("Aff: Aff | Neg: Neg\nResolved: test", encoding="utf-8")
    assert detect_participant_names([path]) == {"aff": None, "neg": None}


def test_detects_name_before_side_template_lines(tmp_path):
    path = tmp_path / "round.txt"
    path.write_text("Francis Chen: Affirmative\nJordan Lee: Negative\n", encoding="utf-8")
    assert detect_participant_names([path]) == {"aff": "Francis Chen", "neg": "Jordan Lee"}


def test_detects_self_introductions_from_side_specific_speeches(tmp_path):
    ac = tmp_path / "1AC.txt"
    nc = tmp_path / "1NC.txt"
    ac.write_text("Good morning judge. My name is Francis Chen and today I affirm the resolution.", encoding="utf-8")
    nc.write_text("Hello. My name is Jordan Lee and I negate today's resolution.", encoding="utf-8")
    speeches = [_speech(ac, "1AC", 1), _speech(nc, "1NC", 3)]
    found = detect_participant_names([ac, nc], speeches)
    assert found == {"aff": "Francis Chen", "neg": "Jordan Lee"}


def test_detected_names_fill_metadata_without_prompting():
    asked = []
    meta = resolve_metadata(
        detected_resolution="A test resolution",
        detected_aff="Francis Chen",
        detected_neg="Jordan Lee",
        prompt=lambda label: asked.append(label) or "",
    )
    assert meta.aff == "Francis Chen"
    assert meta.neg == "Jordan Lee"
    assert meta.sources["aff"] == SOURCE_TRANSCRIPT
    assert meta.sources["neg"] == SOURCE_TRANSCRIPT
    assert asked == []


def test_yaml_still_beats_detected_names():
    meta = resolve_metadata(
        yaml_metadata={"aff": "Yaml Aff", "neg": "Yaml Neg"},
        detected_aff="Detected Aff",
        detected_neg="Detected Neg",
        prompt=lambda _label: "",
    )
    assert meta.aff == "Yaml Aff"
    assert meta.neg == "Yaml Neg"
