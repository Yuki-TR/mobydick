"""scripts/ltx25/cinematic_prompt.py birim testleri (saf Python, GPU yok).

Kurallar iki kılavuzdan pinlendi:
  A) LTX-2 prompting guide  → R-SINGLE-PARAGRAPH, R-SENTENCE-COUNT,
     R-PRESENT-TENSE, R-STRUCTURE-ORDER, R-ONE-CAMERA-MOVEMENT, lens dili,
     R-NO-EMOTION-ABSTRACTS, R-NO-TEXT-OR-LOGO, R-MULTI-SUBJECT-LIMIT.
  B) Prompt writing guide   → R-SUBJECT-MOTION (fiziksel yönetim), negatif
     alan (R-EXPLICIT-STILLNESS), R-NO-VOICEOVER, R-SPATIAL-BLOCKING,
     R-NO-NEGATIVE-PROMPT, R-NO-ASPECT-RATIO.
  Render hataları           → R-EXPLICIT-DIRECTION (ters yön), R-SUBJECT-MOTION
     (kamera etrafında dönme yerine gerçek özne eylemi).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ltx25"))
import cinematic_prompt as m  # noqa: E402


def _shot(**overrides) -> m.ShotSpec:
    base = dict(
        shot_type="medium_close_up",
        subject="a weathered whaler in his fifties in a charcoal greatcoat",
        action="turns his head slowly toward camera, mouth closed",
        environment="a cramped whaleboat cabin at night, rain on the planking",
        camera_move="dolly_in",
        lens="85mm",
        lighting="practical lantern light from the left, deep shadow",
        direction="his shoulders stay square to the lens as he moves closer to camera",
        style="photorealistic historical drama, 35mm film grain, muted desaturated palette",
        audio="the creak of timber, wind against the hull, no dialogue",
    )
    base.update(overrides)
    return m.ShotSpec(**base)


# ---------------------------------------------------------------------------
# Şablon
# ---------------------------------------------------------------------------

def test_render_produces_single_flowing_paragraph():
    prompt = m.render_motion_prompt(_shot())

    assert "\n" not in prompt
    assert not prompt.lstrip().startswith(("-", "*", "•"))
    assert prompt.count("  ") == 0
    assert 4 <= len(m.split_sentences(prompt)) <= 8


def test_render_follows_guide_structure_order():
    prompt = m.render_motion_prompt(_shot()).lower()

    assert prompt.startswith("a medium close-up on an 85mm lens")
    assert "in a cramped whaleboat cabin at night" in prompt
    assert prompt.index("a cramped whaleboat cabin") < prompt.index("the camera dollies in")
    assert prompt.index("the camera dollies in") < prompt.index("35mm film grain")
    assert prompt.index("35mm film grain") < prompt.index("creak of timber")


def test_rendered_prompt_is_valid():
    prompt = m.render_motion_prompt(_shot())

    assert m.validate_motion_prompt(prompt) == []
    assert m.assert_valid_motion_prompt(prompt) == prompt


def test_static_camera_requires_explicit_stillness_but_renderer_supplies_it():
    prompt = m.render_motion_prompt(_shot(camera_move="static", stillness="no hand movement"))

    assert "holds completely still" in prompt
    assert "no hand movement" in prompt
    assert [i.rule for i in m.validate_motion_prompt(prompt)] == []


def test_dialogue_is_quoted_and_audio_clause_survives():
    prompt = m.render_motion_prompt(
        _shot(dialogue="I am not the man you want.", audio="wind, no music")
    )

    assert 'says "I am not the man you want."' in prompt
    assert m.validate_motion_prompt(prompt) == []


def test_unknown_shot_type_camera_move_and_lens_are_rejected():
    with pytest.raises(KeyError, match="shot_type"):
        m.ShotSpec(shot_type="drone", subject="a", action="b",
                   environment="c", camera_move="dolly_in")
    with pytest.raises(KeyError, match="camera_move"):
        m.ShotSpec(shot_type="wide", subject="a", action="b",
                   environment="c", camera_move="spiral")
    with pytest.raises(KeyError, match="lens"):
        m.ShotSpec(shot_type="wide", subject="a", action="b",
                   environment="c", camera_move="static", lens="100mm")


def test_blocking_line_is_rendered_when_supplied():
    prompt = m.render_motion_prompt(
        _shot(
            subject="an old sailor and a young harpooner in oilskins",
            action="stand facing each other across the capstan",
            blocking=(
                "the sailor stands 2 meters from the capstan on the left, the "
                "harpooner 3 meters away on the right, the capstan occludes "
                "their lower bodies"
            ),
        )
    )

    assert "Blocking:" in prompt
    assert m.validate_motion_prompt(prompt) == []


# ---------------------------------------------------------------------------
# Doğrulayıcı — biçim kuralları
# ---------------------------------------------------------------------------

def test_bullet_lists_and_newlines_are_rejected():
    bulleted = "- A wide shot of a harbour\n- The camera dollies in\n- wind"

    assert "R-SINGLE-PARAGRAPH" in {i.rule for i in m.validate_motion_prompt(bulleted)}


def test_semicolon_separated_clauses_are_rejected():
    text = m.render_motion_prompt(_shot()).replace(
        ", wind against the hull", "; wind against the hull"
    )

    assert "R-SINGLE-PARAGRAPH" in {i.rule for i in m.validate_motion_prompt(text)}


def test_too_few_or_too_many_sentences_are_rejected():
    short = (
        "A wide shot of a storm-lashed quay. The camera dollies in. "
        "A sailor walks toward the lens."
    )
    long = m.render_motion_prompt(_shot()) + (
        " Extra padding one here. Extra padding two here. Extra padding three here."
    )

    assert "R-SENTENCE-COUNT" in {i.rule for i in m.validate_motion_prompt(short)}
    assert "R-SENTENCE-COUNT" in {i.rule for i in m.validate_motion_prompt(long)}


def test_empty_prompt_is_rejected():
    assert m.validate_motion_prompt("   ")[0].rule == "R-SINGLE-PARAGRAPH"


# ---------------------------------------------------------------------------
# Doğrulayıcı — zaman ve yapı
# ---------------------------------------------------------------------------

def test_past_tense_is_rejected():
    text = (
        "A wide shot of a storm-lashed quay at dawn, wind and spray. "
        "A whaler walked toward the slipway, his coat flapping. "
        "The camera dollies in, steady, keeping pace. "
        "Photorealistic, muted desaturated palette, film grain. "
        "Rope creak and gulls over the water."
    )

    assert "R-PRESENT-TENSE" in {i.rule for i in m.validate_motion_prompt(text)}


def test_non_finite_words_ending_in_ed_are_not_false_positives():
    prompt = m.render_motion_prompt(_shot(action="leaps toward the open hatch, mouth closed"))

    assert "R-PRESENT-TENSE" not in {i.rule for i in m.validate_motion_prompt(prompt)}


def test_first_sentence_must_name_the_shot_type():
    text = (
        "A whaler stands on a wet quay at dawn, wind and spray, distant rigging. "
        "He moves toward camera down the slipway. "
        "The camera tracks right alongside him. "
        "Photorealistic, film grain, desaturated. "
        "Rope creak, gulls, water against timber."
    )

    assert "R-SHOT-TYPE-FIRST" in {i.rule for i in m.validate_motion_prompt(text)}


def test_out_of_order_sections_are_rejected():
    text = (
        "A wide shot of a fishing village harbour in fog. "
        "The camera dollies in toward the wharf. "
        "A whaler walks toward camera on the quay, coat soaked. "
        "Photorealistic, film grain, desaturated palette. "
        "Rope creak and gulls over black water."
    )

    assert "R-STRUCTURE-ORDER" in {i.rule for i in m.validate_motion_prompt(text)}


def test_missing_lens_is_rejected():
    text = m.render_motion_prompt(
        _shot(lens="35mm", style="photorealistic historical drama, muted desaturated palette")
    ).replace("on a 35mm lens (natural perspective) of", "of")

    assert "R-LENS-VALID" in {i.rule for i in m.validate_motion_prompt(text)}


# ---------------------------------------------------------------------------
# Doğrulayıcı — kamera
# ---------------------------------------------------------------------------

def test_two_camera_movements_in_one_shot_are_rejected():
    text = m.render_motion_prompt(_shot()).replace(
        "The camera dollies in", "The camera dollies in while panning left"
    )

    assert "R-ONE-CAMERA-MOVEMENT" in {i.rule for i in m.validate_motion_prompt(text)}


def test_static_camera_without_explicit_stillness_is_rejected():
    text = m.render_motion_prompt(_shot(camera_move="static", stillness=""))
    text = text.replace("Stillness: ", "Note: ")

    assert "R-EXPLICIT-STILLNESS" in {i.rule for i in m.validate_motion_prompt(text)}


def test_missing_camera_clause_is_rejected():
    text = m.render_motion_prompt(_shot()).replace("The camera dollies in", "The frame drifts")

    assert "R-CAMERA-MOVEMENT-PRESENT" in {i.rule for i in m.validate_motion_prompt(text)}


def test_orbit_only_prompt_is_rejected_because_subject_motion_is_missing():
    text = (
        "A medium close-up on an 85mm lens of a whaler in a charcoal greatcoat, "
        "eyes fixed forward, hands open at his sides. "
        "In a cramped cabin at night, practical lantern light, the framing never changes. "
        "The camera orbits slowly around him, circling around his face. "
        "Photorealistic, film grain, muted desaturated palette. "
        "Timber creak, wind against the hull, no dialogue."
    )

    rules = {i.rule for i in m.validate_motion_prompt(text)}
    assert "R-SUBJECT-MOTION" in rules
    assert "R-ONE-CAMERA-MOVEMENT" not in rules


# ---------------------------------------------------------------------------
# Doğrulayıcı — yönetmen zihniyeti
# ---------------------------------------------------------------------------

def test_missing_direction_is_rejected_to_prevent_reversed_motion():
    text = m.render_motion_prompt(
        _shot(action="turns his head slowly, mouth closed", direction="")
    ).replace("Direction: ", "Note: ")

    assert "R-EXPLICIT-DIRECTION" in {i.rule for i in m.validate_motion_prompt(text)}


def test_internal_emotion_words_are_rejected():
    text = m.render_motion_prompt(_shot()).replace("mouth closed", "looking anxious and afraid")

    assert "R-NO-EMOTION-ABSTRACTS" in {i.rule for i in m.validate_motion_prompt(text)}


def test_abstract_narrative_language_is_rejected():
    text = m.render_motion_prompt(_shot()).replace("mouth closed", "seems to symbolize fate")

    assert "R-NO-ABSTRACT" in {i.rule for i in m.validate_motion_prompt(text)}


def test_voiceover_lines_are_rejected_as_post_production_material():
    text = m.render_motion_prompt(_shot(audio="narrator voiceover reads the opening line"))

    assert "R-NO-VOICEOVER" in {i.rule for i in m.validate_motion_prompt(text)}


def test_negative_prompt_language_is_rejected():
    text = m.render_motion_prompt(_shot(audio="no dialogue, avoid camera motion"))

    assert "R-NO-NEGATIVE-PROMPT" in {i.rule for i in m.validate_motion_prompt(text)}


def test_aspect_ratio_text_is_rejected():
    text = m.render_motion_prompt(_shot(style="16:9 cinematic, film grain"))

    assert "R-NO-ASPECT-RATIO" in {i.rule for i in m.validate_motion_prompt(text)}


def test_on_screen_text_is_rejected():
    text = m.render_motion_prompt(_shot(style="photorealistic, readable text on the cabin wall"))

    assert "R-NO-TEXT-OR-LOGO" in {i.rule for i in m.validate_motion_prompt(text)}


def test_more_than_two_subjects_are_rejected():
    text = m.render_motion_prompt(
        _shot(
            subject=(
                "an old sailor, a young harpooner and a red-haired woman in oilskins"
            ),
            action="stand in a loose triangle on the quay",
            direction="all three face the harbour ahead of them",
            blocking=(
                "the sailor stands 2 meters from the capstan on the left, the "
                "harpooner 3 meters away on the right, the capstan occludes "
                "their lower bodies"
            ),
        )
    )

    assert "R-MULTI-SUBJECT-LIMIT" in {i.rule for i in m.validate_motion_prompt(text)}


def test_two_subjects_without_absolute_distance_are_rejected():
    text = m.render_motion_prompt(
        _shot(
            subject="an old sailor and a young harpooner in oilskins",
            action="stand facing each other across the capstan",
            direction="both face each other across the deck",
        )
    )

    assert "R-SPATIAL-BLOCKING" in {i.rule for i in m.validate_motion_prompt(text)}


# ---------------------------------------------------------------------------
# Ses ve sarmalayıcılar
# ---------------------------------------------------------------------------

def test_missing_audio_cue_is_rejected():
    text = m.render_motion_prompt(_shot(audio=""))
    text = text.replace("Room tone only, no dialogue.", "Color reference only.")

    assert "R-AUDIO-CUE" in {i.rule for i in m.validate_motion_prompt(text)}


def test_assert_valid_raises_with_every_rule_id_listed():
    bad = "A cat on a beach. It was quiet. The camera moved somehow and text appears."

    with pytest.raises(ValueError) as excinfo:
        m.assert_valid_motion_prompt(bad)

    assert "R-" in str(excinfo.value)


def test_sentence_budget_covers_supported_durations():
    for duration in m.SENTENCE_BUDGET:
        low, high = m.SENTENCE_BUDGET[duration]
        assert 4 <= low <= high <= 8


def test_every_documented_rule_id_is_reachable():
    documented = set(m.SHORT_RULES)
    seen: set[str] = set()
    samples = [
        m.render_motion_prompt(_shot(direction="")),
        m.render_motion_prompt(_shot(camera_move="static", stillness="")),
        m.render_motion_prompt(_shot(audio="narrator voiceover, avoid motion, readable text")),
        m.render_motion_prompt(_shot(style="16:9 photorealistic, film grain")),
        m.render_motion_prompt(_shot()).replace("The camera dollies in", "The camera dollies in and pans left"),
        m.render_motion_prompt(_shot()).replace("mouth closed", "walks left while feeling sad"),
        m.render_motion_prompt(_shot(dialogue="Look.")).replace("The camera dollies in", "Nothing happens here."),
    ]
    for sample in samples:
        seen |= {i.rule for i in m.validate_motion_prompt(sample)}
    unknown = seen - documented
    assert not unknown, f"belgelenmemiş kural kodları: {sorted(unknown)}"


def test_vocabulary_tables_match_the_guides():
    assert set(m.SHOT_TYPES) >= {"close_up", "medium", "wide", "aerial", "pov"}
    assert set(m.CAMERA_MOVES) >= {
        "dolly_in", "dolly_out", "pan_left", "tilt_up", "crane_up",
        "track_left", "handheld", "steadicam", "static", "rack_focus",
    }
    assert set(m.LENSES) == {"24mm", "35mm", "50mm", "85mm", "macro", "anamorphic"}
    assert "golden hour" in m.LIGHTING_KEYWORDS
    assert "chiaroscuro" in m.LIGHTING_KEYWORDS
    assert "noir" in " ".join(m.STYLE_MODIFIERS)
