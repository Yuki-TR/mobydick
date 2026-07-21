from pathlib import Path

from book_video.schema import load_project


PILOT_PROJECT = Path("projects/moby_dick_pilot/project.yaml")


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
