"""
Increment 10 — the four paradigm prompts (MVP §4.5) and the --personas registry.

These test the prompts as artifacts: that they exist, differ along the axes the
spec names, and never violate their own vocabulary rules. Story 3.3's kill-switch
depends on that difference being real rather than cosmetic.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.judging import (  # noqa: E402
    DEFAULT_PARADIGMS,
    PARADIGM_LIST,
    PARADIGMS,
    UnknownParadigm,
    build_system_prompt,
    parse_personas,
    valid_persona_names,
)
from src.prompts import load_prompt  # noqa: E402


# --- The registry matches the spec ------------------------------------


def test_there_are_exactly_four_paradigms():
    assert len(PARADIGM_LIST) == 4


def test_paradigm_keys_match_the_documented_names():
    assert DEFAULT_PARADIGMS == ["lay", "educated_lay", "traditional", "circuit"]


def test_display_names_match_mvp_section_4_5():
    assert [p.display_name for p in PARADIGM_LIST] == [
        "Lay Parent", "Educated Lay", "Traditional LD", "Technical Circuit"
    ]


@pytest.mark.parametrize(
    "key,cap",
    [("lay", 80), ("educated_lay", 100), ("traditional", 150), ("circuit", 150)],
)
def test_rfd_word_caps_match_mvp_section_6(key, cap):
    """
    Tightened 2026-08-20 (Story 4 closed) to control costs. RFD becomes a tight
    summary (2-3 sentences), KEY VOTING ISSUES become one-line bullets. The longer
    RFDs prompted multi-paragraph exposition that overran even the raised caps.
    """
    assert PARADIGMS[key].rfd_word_cap == cap


def test_caps_still_differentiate_the_paradigms():
    """Raising them must not flatten the spectrum they exist to create."""
    caps = [PARADIGMS[k].rfd_word_cap for k in DEFAULT_PARADIGMS]
    assert caps == sorted(caps)
    assert caps[-1] >= 1.5 * caps[0]  # 150/80 = 1.875x, maintains differentiation


@pytest.mark.parametrize("key", DEFAULT_PARADIGMS)
def test_every_paradigm_gives_feedback_to_the_debaters(key):
    """MS debaters get more from the feedback than from the verdict."""
    assert "FEEDBACK" in build_system_prompt(key)


@pytest.mark.parametrize("key", ["educated_lay", "traditional", "circuit"])
def test_style_anchored_paradigms_carry_a_human_example(key):
    assert "How Your Ballot Should Read" in load_prompt(PARADIGMS[key].prompt_name)


def test_lay_has_no_style_anchor():
    """No lay-parent ballot exists in the reference set; do not fabricate one."""
    assert "How Your Ballot Should Read" not in load_prompt("judge_lay")


def test_style_anchors_carry_no_student_names():
    """The reference RFDs were written about real children."""
    for key in ("educated_lay", "traditional", "circuit"):
        assert "Ethan" not in load_prompt(PARADIGMS[key].prompt_name)
    assert "Ethan" not in load_prompt("reference/human_rfd_examples")


def test_ballot_filenames_follow_the_storage_convention():
    assert PARADIGMS["circuit"].ballot_filename == "judge_circuit.md"


# --- Story 3.2: --personas parsing ------------------------------------


def test_no_flag_means_every_paradigm():
    assert parse_personas(None) == DEFAULT_PARADIGMS


def test_all_keyword_means_every_paradigm():
    assert parse_personas("all") == DEFAULT_PARADIGMS


def test_a_subset_selects_only_those():
    assert parse_personas("lay,circuit") == ["lay", "circuit"]


def test_whitespace_and_case_are_tolerated():
    assert parse_personas(" Lay , CIRCUIT ") == ["lay", "circuit"]


def test_selection_is_returned_in_registry_order():
    """Ballots and the diff always read least- to most-technical."""
    assert parse_personas("circuit,lay") == ["lay", "circuit"]


def test_duplicates_are_collapsed():
    assert parse_personas("lay,lay") == ["lay"]


def test_unknown_persona_error_matches_the_acceptance_criteria():
    with pytest.raises(UnknownParadigm) as caught:
        parse_personas("lyd")
    assert str(caught.value) == (
        "Unknown persona 'lyd'. Valid: lay, educated_lay, traditional, circuit, all."
    )


def test_removed_paradigms_are_rejected():
    """Flow and Framework were dropped when the spec moved to four paradigms."""
    for removed in ("flow", "framework"):
        with pytest.raises(UnknownParadigm):
            parse_personas(removed)


def test_valid_names_list_includes_all():
    assert valid_persona_names() == "lay, educated_lay, traditional, circuit, all"


# --- The prompt files exist and are substantive -----------------------


@pytest.mark.parametrize("paradigm", PARADIGM_LIST, ids=lambda p: p.key)
def test_every_paradigm_has_a_prompt_file(paradigm):
    assert len(load_prompt(paradigm.prompt_name)) > 1000


@pytest.mark.parametrize("paradigm", PARADIGM_LIST, ids=lambda p: p.key)
def test_every_prompt_has_the_sections_the_template_requires(paradigm):
    """MVP §6 persona template."""
    text = load_prompt(paradigm.prompt_name)
    for heading in (
        "## Your Paradigm",
        "## What You Prioritize",
        "## What You Accept As Legitimate",
        "## What You Deprioritize Or React Negatively To",
        "## Your Vocabulary And Voice",
        "## Your Ballot Format",
    ):
        assert heading in text, f"{paradigm.key} missing {heading}"


@pytest.mark.parametrize("paradigm", PARADIGM_LIST, ids=lambda p: p.key)
def test_every_prompt_states_its_word_cap(paradigm):
    assert f"{paradigm.rfd_word_cap} words maximum" in load_prompt(paradigm.prompt_name)


@pytest.mark.parametrize("paradigm", PARADIGM_LIST, ids=lambda p: p.key)
def test_no_prompt_asks_for_a_numeric_confidence(paradigm):
    """Story 4.2: lean labels only, never percentages."""
    text = load_prompt(paradigm.prompt_name).lower()
    assert "% confident" not in text
    assert "percentage" not in text


# --- The paradigms actually differ ------------------------------------


def test_the_four_prompts_are_not_near_duplicates():
    texts = [load_prompt(p.prompt_name) for p in PARADIGM_LIST]
    for index, first in enumerate(texts):
        for second in texts[index + 1:]:
            shared = set(first.lower().split()) & set(second.lower().split())
            union = set(first.lower().split()) | set(second.lower().split())
            assert len(shared) / len(union) < 0.55, "paradigms read too alike"


def test_lay_parent_is_forbidden_from_using_jargon_in_its_ballot():
    """
    Story 3.3: "Lay Parent never says kritik".

    The prompt does name jargon terms — in the list of things this paradigm
    refuses to credit — so the requirement is an explicit instruction never to
    use them in the ballot, not the absence of the words from the prompt.
    """
    text = load_prompt("judge_lay")
    # Substrings kept short: the prompt is hard-wrapped at 80 columns.
    assert "not even to dismiss it" in text
    assert "Never use a piece of debate" in text
    assert "a lot of terms I" in text
    assert "ran a K." in text  # the example of what NOT to write


def test_lay_parent_is_told_not_to_credit_the_technical_vocabulary():
    text = load_prompt("judge_lay").lower()
    for term in ("kritik", "topicality", "condo", "pik", "spike"):
        assert term in text, f"lay prompt should name {term} as jargon it ignores"


def test_circuit_uses_circuit_vocabulary():
    text = load_prompt("judge_circuit").lower()
    for term in ("kritik", "pik", "condo", "perm", "spike", "extend"):
        assert term in text


def test_educated_lay_is_told_to_avoid_circuit_shorthand():
    text = load_prompt("judge_educated_lay").lower()
    assert "do not use circuit shorthand" in text


def test_only_circuit_welcomes_speed():
    """The clearest tolerance split in the set."""
    circuit = load_prompt("judge_circuit").lower()
    assert "speed is not a vice" in circuit
    assert "do not deduct for speed" in circuit

    for key in ("lay", "educated_lay", "traditional"):
        text = load_prompt(PARADIGMS[key].prompt_name).lower()
        penalized = any(
            phrase in text
            for phrase in ("speed", "spreading", "unfollowable", "too fast")
        )
        assert penalized, f"{key} should react to fast or dense delivery"
        assert "speed is not a vice" not in text


def test_lay_and_circuit_disagree_about_dropped_arguments():
    """The clearest paradigm split, and a likely source of divergence."""
    assert "did not have a flow" in load_prompt("judge_lay").lower()
    assert "conceded argument is true" in load_prompt("judge_circuit").lower()


def test_only_circuit_will_vote_on_a_kritik():
    assert "vote on a k" in load_prompt("judge_circuit").lower()
    assert "will not vote on one" in load_prompt("judge_traditional").lower()


# --- Assembled system prompts ----------------------------------------


@pytest.mark.parametrize("key", DEFAULT_PARADIGMS)
def test_system_prompt_appends_the_shared_standards(key):
    prompt = build_system_prompt(key)
    assert "# APPENDIX — Shared Standards" in prompt
    assert "The Ballot Form" in prompt


@pytest.mark.parametrize("key", DEFAULT_PARADIGMS)
def test_persona_text_comes_before_the_standards(key):
    """Paradigm framing must govern how the shared standards are read."""
    prompt = build_system_prompt(key)
    assert prompt.index("## Your Paradigm") < prompt.index("# APPENDIX")


@pytest.mark.parametrize("key", DEFAULT_PARADIGMS)
def test_system_prompt_carries_the_common_ballot_fields(key):
    prompt = build_system_prompt(key)
    for field in ("WINNER:", "LEAN:", "RFD:", "SPEAKER POINTS:"):
        assert field in prompt


@pytest.mark.parametrize(
    "key,section",
    [
        ("lay", "WHAT STUCK WITH ME"),
        ("educated_lay", "MY REASONS"),
        ("traditional", "KEY VOTING ISSUES"),
        ("circuit", "KEY VOTING ISSUES"),
    ],
)
def test_each_paradigm_has_its_own_final_ballot_section(key, section):
    """
    The shared ballot block was itself driving convergence: requiring numbered
    KEY VOTING ISSUES forced every persona into issue-based adjudication, which a
    lay parent has no concept of.
    """
    assert section in build_system_prompt(key)


def test_lay_is_not_asked_for_voting_issues():
    assert "KEY VOTING ISSUES" not in build_system_prompt("lay")


def test_shared_standards_forbid_percentages():
    assert "Never** state a percentage" in load_prompt("shared/ld_standards")


def test_shared_standards_carry_no_evaluation_rubric():
    """
    Handing four judges one weighted rubric made them score alike. The rubric now
    lives in judge_traditional.md, whose paradigm it actually describes.
    """
    text = load_prompt("shared/ld_standards")
    for leaked in ("25%", "30%", "Value/Criterion framework —", "evidence tag"):
        assert leaked not in text, f"shared standards still carry {leaked!r}"
    assert "Value/criterion framework — 30%" in load_prompt("judge_traditional")


def test_shared_standards_carry_no_speech_nomenclature():
    """A lay parent does not know what a 1AR is; naming it teaches them to be a judge."""
    text = load_prompt("shared/ld_standards")
    for label in ("1AC", "CX1", "1NC", "1AR", "2NR", "2AR"):
        assert label not in text, f"shared standards still name {label}"
    # Traditional is told the names explicitly; Circuit is told to cite the speech.
    assert "1AR" in load_prompt("judge_traditional")
    assert "name the speech" in load_prompt("judge_circuit")
    assert "1AR" not in load_prompt("judge_lay")


def test_recall_differs_by_paradigm():
    """The mechanism intended to break convergence."""
    assert "You took no notes" in load_prompt("judge_lay")
    assert "not trained to flow" in load_prompt("judge_educated_lay")
    assert "complete flow" in load_prompt("judge_circuit").lower()


def test_only_lay_may_not_cite_evidence():
    assert "cannot cite evidence" in load_prompt("judge_lay")
    for key in ("traditional", "circuit"):
        assert "cite evidence by author" in load_prompt(PARADIGMS[key].prompt_name)


def test_only_lay_gets_a_prior_belief_tiebreak():
    lay = load_prompt("judge_lay")
    assert "tie-break only" in lay
    assert "not supposed to decide on personal belief" in lay
    for key in ("educated_lay", "traditional", "circuit"):
        assert "Your Own Views On The Topic" not in load_prompt(PARADIGMS[key].prompt_name)


def test_framework_layer_guidance_is_scaled_by_paradigm():
    """Lay cannot do framework layering; Educated Lay gets a lighter version."""
    assert "Resolve The Framework Layer First" in load_prompt("judge_traditional")
    assert "Resolve The Framework Layer First" in load_prompt("judge_circuit")
    assert "Settle The Standard Before Weighing" in load_prompt("judge_educated_lay")
    assert "Framework Layer" not in load_prompt("judge_lay")


def test_offense_defense_reaches_the_technical_paradigms():
    """The error every persona made on both human-verified rounds."""
    for key in ("traditional", "circuit"):
        text = load_prompt(PARADIGMS[key].prompt_name)
        assert "Defense alone never wins" in text
        assert "Evidence Turns" in text
    assert "not a reason to prefer the side doing the damaging" in load_prompt(
        "judge_educated_lay"
    )


def test_every_paradigm_is_told_to_apply_an_uncontested_standard():
    """Substituting your own weighing for an uncontested one is intervention."""
    shared = load_prompt("shared/ld_standards")
    assert "that test governs" in shared
    assert 'I am voting for this side because they showed' in shared


def test_building_an_unknown_persona_raises():
    with pytest.raises(UnknownParadigm):
        build_system_prompt("nope")


# --- No preset gender for debaters ------------------------------------

GENDERED = re.compile(r"\b(she|he|her|him|hers|his)\b", re.I)


@pytest.mark.parametrize("paradigm", PARADIGM_LIST, ids=lambda p: p.key)
def test_no_prompt_presets_a_debaters_gender(paradigm):
    """
    These are real middle-school students. A name doesn't reveal pronouns, and a
    wrong guess misgenders a child in a ballot they may well read.
    """
    text = load_prompt(paradigm.prompt_name)
    assert not GENDERED.search(text), (
        f"{paradigm.key} prompt contains a gendered pronoun: "
        f"{GENDERED.search(text).group(0)!r}"
    )


def test_shared_standards_forbid_assuming_gender():
    text = load_prompt("shared/ld_standards")
    assert "Never assume a debater's gender" in text
    assert "they/them" in text


def test_shared_standards_offer_gender_neutral_alternatives():
    text = load_prompt("shared/ld_standards")
    assert "the affirmative" in text
    assert "they/them" in text


@pytest.mark.parametrize("key", DEFAULT_PARADIGMS)
def test_every_assembled_prompt_carries_the_no_gender_rule(key):
    """The rule ships in the appendix, so every persona receives it."""
    assert "Never assume a debater's gender" in build_system_prompt(key)
