from src.metadata import SOURCE_AFF_FLAG, SOURCE_NEG_FLAG, resolve_metadata


def test_cli_participant_overrides_beat_transcript_detection_but_not_yaml():
    meta = resolve_metadata(
        cli_aff="Edited Aff",
        cli_neg="Edited Neg",
        detected_aff="Detected Aff",
        detected_neg="Detected Neg",
        prompt=lambda _label: "",
    )
    assert meta.aff == "Edited Aff"
    assert meta.neg == "Edited Neg"
    assert meta.sources["aff"] == SOURCE_AFF_FLAG
    assert meta.sources["neg"] == SOURCE_NEG_FLAG

    yaml_meta = resolve_metadata(
        yaml_metadata={"aff": "YAML Aff", "neg": "YAML Neg"},
        cli_aff="Edited Aff",
        cli_neg="Edited Neg",
        prompt=lambda _label: "",
    )
    assert yaml_meta.aff == "YAML Aff"
    assert yaml_meta.neg == "YAML Neg"
