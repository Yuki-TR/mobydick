from pathlib import Path

from book_video.adaptation import load_adaptation
from book_video.schema import load_project


PILOT_PROJECT = Path("projects/moby_dick_pilot/project.yaml")
FIVE_MINUTE_ADAPTATION = Path("projects/moby_dick_pilot/adaptation.yaml")


def test_pilot_uses_brian_multilingual_as_the_single_narrator() -> None:
    project = load_project(PILOT_PROJECT)

    assert set(project.speakers) == {"ishmael"}
    assert project.speakers["ishmael"].voice == "en-US-BrianMultilingualNeural"
    assert project.speakers["ishmael"].rate == "+0%"
    assert project.speakers["ishmael"].pitch == "+0Hz"


def test_pilot_motion_prompts_do_not_imply_visible_speech() -> None:
    project = load_project(PILOT_PROJECT)

    for scene in project.scenes:
        prompt = scene.motion_prompt.lower()
        assert "mouth closed" in prompt
        assert "no visible speech" in prompt


def test_five_minute_adaptation_has_two_shared_narration_modes() -> None:
    adaptation = load_adaptation(FIVE_MINUTE_ADAPTATION)

    assert adaptation.default_mode == "faithful"
    assert adaptation.target_duration_sec == 300
    assert (adaptation.output.width, adaptation.output.height) == (1920, 1080)
    assert adaptation.narrator.voice == "en-US-BrianMultilingualNeural"
    assert len(adaptation.scenes) == 22
    assert sum(scene.duration_ms for scene in adaptation.scenes) == 300_000
    assert len({scene.image for scene in adaptation.scenes}) == 22
    assert len(
        {scene.image for scene in adaptation.scenes}
        | {scene.end_image for scene in adaptation.scenes}
    ) == 23
    assert all(
        current.end_image == following.image
        for current, following in zip(adaptation.scenes, adaptation.scenes[1:])
    )
    assert [scene.duration_ms for scene in adaptation.scenes] == [14_000] * 14 + [
        13_000
    ] * 8
    assert all(scene.ambience.gain_db <= -22 for scene in adaptation.scenes)

    faithful_words = sum(
        len(scene.narration.faithful.split()) for scene in adaptation.scenes
    )
    modern_words = sum(
        len(scene.narration.modern.split()) for scene in adaptation.scenes
    )
    assert 550 <= faithful_words <= 800
    assert 400 <= modern_words <= 650
