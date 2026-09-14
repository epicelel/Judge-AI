"""
Story 2.1 — Detect speech boundaries in a single-file transcript.

All mocked: the real call is a manual check at the phase boundary.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.detection import (  # noqa: E402
    DetectedSpeech,
    DetectionError,
    detect_structure,
    extract_json,
    locate_marker,
    mismatch_message,
    missing_speeches,
    parse_detection,
    split_transcript,
)
from src.prompts import load_prompt  # noqa: E402
from src.structure import SOURCE_MODEL  # noqa: E402
from tests.conftest import FakeBedrockClient  # noqa: E402

TRANSCRIPT = (
    "[00:04] My name is Drew and I strongly affirm the resolution that the "
    "possession of nuclear weapons is immoral. My value is morality. "
    "I stand ready for cross-examination.\n\n"
    "[03:00] And your criterion is preventing death, is that true? Yes it is. "
    "How many subpoints do you have?\n\n"
    "[06:00] The research is clear and history backs it up. Nuclear weapons "
    "have kept the world from war since 1945. I negate the resolution.\n\n"
    "[09:00] I have a few questions about your deterrence argument. "
    "Doesn't that prove nuclear weapons are immoral?\n\n"
    "[12:00] Extend my framework. Preventing death is paramount and my "
    "opponent concedes the accident risk.\n\n"
    "[15:00] Extend deterrence. It has worked for eighty years and safety "
    "mechanisms prevent accidental launch.\n\n"
    "[18:00] Vote affirmative to prevent existential risk. One nuclear war "
    "ends humanity, which is unacceptable."
)

FULL_PAYLOAD = {
    "speeches": [
        {"label": "1AC", "speaker": "Aff", "start_marker": "My name is Drew and I strongly affirm"},
        {"label": "CX1", "speaker": "Both", "start_marker": "And your criterion is preventing death"},
        {"label": "1NC", "speaker": "Neg", "start_marker": "The research is clear and history backs"},
        {"label": "CX2", "speaker": "Both", "start_marker": "I have a few questions about your deterrence"},
        {"label": "1AR", "speaker": "Aff", "start_marker": "Extend my framework. Preventing death is paramount"},
        {"label": "2NR", "speaker": "Neg", "start_marker": "Extend deterrence. It has worked for eighty"},
        {"label": "2AR", "speaker": "Aff", "start_marker": "Vote affirmative to prevent existential risk"},
    ],
    "resolution": {
        "text": "The possession of nuclear weapons is immoral.",
        "quote": "I strongly affirm the resolution that the possession of nuclear weapons is immoral.",
        "confidence": "high",
    },
    "notes": "",
}


def client_returning(payload) -> FakeBedrockClient:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return FakeBedrockClient(responses=[text])


# --- Given a well-formed transcript, 7 speeches are labeled -------------


def test_all_seven_ld_speeches_are_identified():
    result, speeches = detect_structure(client_returning(FULL_PAYLOAD), TRANSCRIPT)
    assert result.labels == ["1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR"]
    assert len(speeches) == 7


def test_speakers_come_from_the_canonical_sequence():
    _result, speeches = detect_structure(client_returning(FULL_PAYLOAD), TRANSCRIPT)
    assert [s.speaker for s in speeches] == [
        "Aff", "Both", "Neg", "Both", "Aff", "Neg", "Aff"
    ]


def test_detected_speeches_are_marked_as_model_sourced():
    _result, speeches = detect_structure(client_returning(FULL_PAYLOAD), TRANSCRIPT)
    assert all(s.source == SOURCE_MODEL for s in speeches)


def test_each_segment_contains_its_own_text_only():
    _result, speeches = detect_structure(client_returning(FULL_PAYLOAD), TRANSCRIPT)
    first = speeches[0].path.read_text()
    assert "My name is Drew" in first
    assert "I negate the resolution" not in first  # 1NC text stayed in the 1NC


def test_the_last_segment_runs_to_the_end_of_the_transcript():
    _result, speeches = detect_structure(client_returning(FULL_PAYLOAD), TRANSCRIPT)
    assert "unacceptable" in speeches[-1].path.read_text()


def test_splitting_is_lossless_from_the_first_speech_onward():
    """Every word from the 1AC to the end lands in exactly one segment."""
    result, speeches = detect_structure(client_returning(FULL_PAYLOAD), TRANSCRIPT)
    body = TRANSCRIPT[result.preamble_chars:]
    segment_words = sum(len(s.path.read_text().split()) for s in speeches)
    assert segment_words == len(body.split())


def test_every_segment_is_verbatim_transcript_text():
    """The model indexes the transcript; it must never rewrite it."""
    _result, speeches = detect_structure(client_returning(FULL_PAYLOAD), TRANSCRIPT)
    for speech in speeches:
        assert speech.path.read_text() in TRANSCRIPT


def test_dropped_preamble_is_reported_not_silent():
    result, _speeches = detect_structure(client_returning(FULL_PAYLOAD), TRANSCRIPT)
    assert result.preamble_chars == len("[00:04] ")


def test_detection_is_deterministic_and_cheap_on_output():
    """Temperature 0, and markers rather than echoed text."""
    client = client_returning(FULL_PAYLOAD)
    detect_structure(client, TRANSCRIPT)
    assert client.calls[0]["temperature"] == 0.0


def test_the_detection_prompt_is_sent_as_the_system_prompt():
    client = client_returning(FULL_PAYLOAD)
    detect_structure(client, TRANSCRIPT)
    assert client.calls[0]["system"] == load_prompt("shared/structure_detection")
    assert client.calls[0]["user"] == TRANSCRIPT


# --- Given a missing speech, report the mismatch -----------------------


def test_missing_speeches_are_identified():
    assert missing_speeches(["1AC", "CX1", "1NC", "CX2", "2NR"]) == ["1AR", "2AR"]


def test_nothing_missing_when_all_seven_present():
    assert missing_speeches(["1AC", "CX1", "1NC", "CX2", "1AR", "2NR", "2AR"]) == []


def test_mismatch_message_matches_the_acceptance_criteria():
    assert mismatch_message(5, ["1AR", "2AR"]) == (
        "Expected 7 speeches, found 5. Missing: 1AR, 2AR. Proceed anyway?"
    )


def test_partial_transcript_yields_only_the_speeches_present():
    payload = {"speeches": FULL_PAYLOAD["speeches"][:5], "resolution": {}, "notes": ""}
    result, speeches = detect_structure(client_returning(payload), TRANSCRIPT)
    assert len(speeches) == 5
    assert missing_speeches(result.labels) == ["2NR", "2AR"]


# --- JSON extraction --------------------------------------------------


def test_plain_json_is_parsed():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json_is_parsed():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_wrapped_in_prose_is_parsed():
    assert extract_json('Here is the result:\n{"a": 1}\nHope that helps.') == {"a": 1}


def test_unparseable_response_raises_with_a_pointer_to_verbose():
    with pytest.raises(DetectionError) as caught:
        extract_json("I could not analyze that transcript.")
    assert "--verbose" in str(caught.value)


# --- Marker location --------------------------------------------------


def test_exact_marker_is_located():
    assert locate_marker("hello world foo", "world") == 6


def test_marker_with_different_whitespace_still_matches():
    assert locate_marker("hello   world", "hello world") == 0


def test_marker_with_different_punctuation_still_matches():
    assert locate_marker("Extend my framework. Preventing death", "Extend my framework Preventing") == 0


def test_absent_marker_returns_none():
    assert locate_marker("hello world", "goodbye") is None


def test_search_starts_after_the_previous_speech():
    """A repeated phrase must not send a later speech backwards."""
    text = "alpha beta alpha gamma"
    assert locate_marker(text, "alpha", search_from=5) == 11


def test_unmatched_markers_are_reported_not_dropped_silently():
    payload = {
        "speeches": [
            {"label": "1AC", "speaker": "Aff", "start_marker": "My name is Drew"},
            {"label": "1NC", "speaker": "Neg", "start_marker": "this phrase is not in the transcript"},
        ],
        "resolution": {},
        "notes": "",
    }
    result, speeches = detect_structure(client_returning(payload), TRANSCRIPT)
    assert result.unmatched_markers == ["1NC"]
    assert len(speeches) == 1


def test_speeches_are_split_left_to_right():
    speeches = [
        DetectedSpeech("1AC", "Aff", "alpha"),
        DetectedSpeech("1NC", "Neg", "beta"),
    ]
    segments, unmatched = split_transcript("alpha one beta two", speeches)
    assert unmatched == []
    assert segments[0][1] == "alpha one"
    assert segments[1][1] == "beta two"


# --- Malformed payloads ----------------------------------------------


def test_entries_without_a_marker_are_skipped():
    payload = {"speeches": [{"label": "1AC", "start_marker": ""}], "resolution": {}}
    assert parse_detection(payload).speeches == []


def test_lowercase_labels_are_normalized():
    payload = {"speeches": [{"label": "1ac", "start_marker": "My name is Drew"}]}
    assert parse_detection(payload).speeches[0].label == "1AC"


def test_absent_speeches_key_yields_an_empty_result():
    assert parse_detection({}).speeches == []


def test_resolution_is_extracted_when_present():
    result = parse_detection(FULL_PAYLOAD)
    assert result.resolution_text == "The possession of nuclear weapons is immoral."
    assert result.resolution_confidence == "high"


def test_absent_resolution_defaults_to_low_confidence():
    result = parse_detection({"speeches": [], "resolution": {"text": None}})
    assert result.resolution_text is None
    assert result.resolution_confidence == "low"


# --- Works with the dry-run client -----------------------------------


def test_dry_run_client_makes_no_call_and_yields_no_speeches():
    from src.bedrock_client import DryRunBedrockClient

    client = DryRunBedrockClient(echo=False)
    with pytest.raises(DetectionError):
        detect_structure(client, TRANSCRIPT)  # placeholder text isn't JSON
    assert client.call_count == 1


# --- Regression: bugs found by the first real call --------------------


def test_marker_spanning_an_inline_timestamp_is_located():
    """
    Found on a real 36KB Otter transcript.

    The model quoted a marker running across an inline `[00:09]` timestamp, so
    the literal string was absent and the whole 1AC was discarded as preamble
    while the run reported "missing: none".
    """
    transcript = (
        "[00:04] Okay. I will start on my first word, which is now.\n"
        "[00:09] My name is Drew and I strongly affirm the resolution."
    )
    marker = "Okay. I will start on my first word, which is now. My name is Drew"
    assert locate_marker(transcript, marker) == transcript.index("Okay")


def test_marker_is_located_from_a_prefix_when_its_tail_diverges():
    transcript = "Extend my framework because preventing death is paramount."
    marker = "Extend my framework because preventing death outweighs everything else"
    assert locate_marker(transcript, marker) == 0


def test_a_speech_that_cannot_be_located_is_reported_as_missing():
    """`labels` must describe what was split, not what the model proposed."""
    payload = {
        "speeches": [
            {"label": "1AC", "speaker": "Aff", "start_marker": "nowhere in this text at all"},
            {"label": "CX1", "speaker": "Both", "start_marker": "And your criterion is preventing death"},
        ],
        "resolution": {},
        "notes": "",
    }
    result, speeches = detect_structure(client_returning(payload), TRANSCRIPT)
    assert result.labels == ["CX1"]
    assert "1AC" in missing_speeches(result.labels)
    assert result.unmatched_markers == ["1AC"]
    assert len(speeches) == 1


def test_a_file_header_before_the_first_speech_is_dropped():
    transcript = (
        "TRANSCRIPT\n====\n[Paste the full debate transcript here]\n\n"
        "My name is Drew and I strongly affirm the resolution."
    )
    payload = {
        "speeches": [{"label": "1AC", "speaker": "Aff", "start_marker": "My name is Drew"}],
        "resolution": {},
    }
    result, speeches = detect_structure(client_returning(payload), transcript)
    assert "TRANSCRIPT" not in speeches[0].path.read_text()
    assert result.preamble_chars == transcript.index("My name")
