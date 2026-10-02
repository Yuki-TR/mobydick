"""``scripts/ltx25/moby_dick_shots.py`` dönüşümünün doğrulama testleri.

Kapsam:
  * adaptation.yaml'daki 22 sahnenin HEPSİ bir ShotSpec'e karşılık gelir
    (eksik/fazla sahne yok, sıra birebir aynı).
  * Render edilen 22 prompt'un tamamı ``validate_motion_prompt`` süzgecinden
    **temiz** geçer — sahne başına 6-8 ihlal gelen serbest metin sürümü bu
    testin kendisi tarafından da reddedilir (regresyon kanıtı).
  * Şema bütünlüğü: ShotSpec alanları dolu, kamera hareketi tek ve gerçek bir
    hareket, yön kilidi (R-EXPLICIT-DIRECTION) ve hareketsizlik yazılı.
  * Kalite kaybı yok: sahne anlatısı korunur (konuşma yok, VOICEOVER yok,
    okunabilir metin yok, aspect-ratio yok).

Çalıştırma:
    uv run pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-a tests/test_moby_dick_shots.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ltx25"))

import cinematic_prompt as cp  # noqa: E402
from moby_dick_shots import SCENE_IDS, SCENE_SHOTS, shot_for_scene_id  # noqa: E402

ADAPTATION = ROOT / "projects" / "moby_dick_pilot" / "adaptation.yaml"

SCENES = pytest.mark.parametrize("scene_id", SCENE_IDS, ids=SCENE_IDS)


def _adaptation_scenes() -> list[dict]:
    data = yaml.safe_load(ADAPTATION.read_text(encoding="utf-8"))
    return list(data["scenes"])


def _prompt(scene_id: str) -> str:
    return cp.render_motion_prompt(shot_for_scene_id(scene_id))


# ---------------------------------------------------------------------------
# Kapsam: 22 sahnenin tamamı
# ---------------------------------------------------------------------------

def test_adaptation_has_22_scenes():
    assert len(_adaptation_scenes()) == 22
    assert len(SCENE_IDS) == 22
    assert len(SCENE_SHOTS) == 22


def test_scene_ids_and_order_match_adaptation_yaml():
    yaml_ids = [s["id"] for s in _adaptation_scenes()]
    assert list(SCENE_IDS) == yaml_ids
    assert set(SCENE_SHOTS) == set(yaml_ids)


def test_every_scene_id_lookup_works():
    for scene_id in SCENE_IDS:
        assert isinstance(shot_for_scene_id(scene_id), cp.ShotSpec)


def test_unknown_scene_id_raises_keyerror():
    with pytest.raises(KeyError):
        shot_for_scene_id("no_such_scene")


# ---------------------------------------------------------------------------
# Render + doğrulama: dönüşümün asıl sözleşmesi
# ---------------------------------------------------------------------------

@SCENES
def test_rendered_prompt_passes_every_rule(scene_id: str):
    assert cp.validate_motion_prompt(_prompt(scene_id)) == []


@SCENES
def test_rendered_prompt_is_single_paragraph(scene_id: str):
    prompt = _prompt(scene_id)
    assert "\n" not in prompt
    assert "  " not in prompt
    assert 4 <= len(cp.split_sentences(prompt)) <= 8


@SCENES
def test_shot_type_opens_the_prompt(scene_id: str):
    first = cp.split_sentences(_prompt(scene_id))[0]
    assert first.startswith(tuple(cp.SHOT_TYPES.values()))


@SCENES
def test_lens_is_from_the_dictionary(scene_id: str):
    shot = shot_for_scene_id(scene_id)
    assert shot.lens in cp.LENSES
    assert f"{shot.lens} lens" in _prompt(scene_id)


@SCENES
def test_subject_motion_and_direction_are_explicit(scene_id: str):
    """İlk render hatalarının panzehiri: fiil + yön kilidi."""
    prompt = _prompt(scene_id)
    low = prompt.lower()
    assert any(v in low for v in cp.MOTION_VERBS)
    direction = next(
        (s for s in cp.split_sentences(prompt) if s.lower().startswith("direction:")),
        "",
    )
    assert direction, f"{scene_id}: yön cümlesi yok (R-EXPLICIT-DIRECTION)"
    assert any(t in direction.lower() for t in cp.DIRECTION_TOKENS)


@SCENES
def test_exactly_one_camera_movement(scene_id: str):
    assert len(cp._find_camera_moves(_prompt(scene_id))) == 1


@SCENES
def test_required_fields_are_populated(scene_id: str):
    shot = shot_for_scene_id(scene_id)
    for field in ("subject", "action", "environment", "lighting", "style", "audio"):
        assert getattr(shot, field).strip(), f"{scene_id}.{field} boş"
    assert shot.stillness.strip(), f"{scene_id}: negatif alan/hareketsizlik yazılmamış"
    assert shot.dialogue == "", f"{scene_id}: diyalog prompt'a girmemeli (VO post)"


@SCENES
def test_style_is_shared_period_drama_look(scene_id: str):
    assert "photorealistic" in _prompt(scene_id).lower()
    assert "35mm film grain" in _prompt(scene_id).lower()


@SCENES
def test_no_voiceover_text_or_aspect_ratio(scene_id: str):
    low = _prompt(scene_id).lower()
    assert not cp._VOICEOVER_RE.search(low)
    assert not any(w in low for w in cp.TEXT_WORDS)
    assert not cp._ASPECT_RE.search(low)
    assert not cp._NEGATIVE_RE.search(_prompt(scene_id))


@SCENES
def test_multi_subject_scenes_report_absolute_blocking(scene_id: str):
    sentences = cp.split_sentences(_prompt(scene_id))
    scope = " ".join(
        s for s in sentences
        if s == sentences[0] or s.lower().startswith("blocking:")
    )
    shot = shot_for_scene_id(scene_id)
    if cp._count_subjects(scope) == 2:
        assert shot.blocking.strip(), f"{scene_id}: 2 özne, blocking boş"
        assert re.search(r"\b\d+(\.\d+)?\s*(m\b|meters?|metres?)", _prompt(scene_id).lower())


# ---------------------------------------------------------------------------
# Kalite: anlatı korunur, iç duygu / soyut anlatım yok
# ---------------------------------------------------------------------------

@SCENES
def test_no_interior_emotion_or_abstract_language(scene_id: str):
    low = _prompt(scene_id).lower()
    for word in cp.EMOTION_WORDS:
        assert not re.search(rf"\b{re.escape(word)}\w*\b", low), (
            f"{scene_id}: iç duygu ifadesi {word!r}"
        )
    for word in cp.ABSTRACT_WORDS:
        assert word not in low, f"{scene_id}: soyut anlatım {word!r}"


def test_original_free_text_prompts_are_rejected():
    """Regresyon kanıtı: dönüşüm öncesi serbest metinler kurallara uymuyordu."""
    violating = 0
    for scene in _adaptation_scenes():
        if cp.validate_motion_prompt(" ".join(scene["motion_prompt"].split())):
            violating += 1
    assert violating == 22, f"beklenen 22 ihlalli eski prompt, gelen {violating}"


def test_conversion_reduces_issue_count_to_zero():
    before = sum(
        len(cp.validate_motion_prompt(" ".join(s["motion_prompt"].split())))
        for s in _adaptation_scenes()
    )
    after = sum(len(cp.validate_motion_prompt(_prompt(sid))) for sid in SCENE_IDS)
    assert after == 0
    assert before > 100, f"eski metinler beklenenden az ihlal içeriyor: {before}"