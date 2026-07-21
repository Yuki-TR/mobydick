from __future__ import annotations

from copy import deepcopy

import pytest

from book_video.schema import (
    ProjectValidationError,
    load_project,
    validate_project,
    validate_project_assets,
)


def test_load_project_parses_the_public_yaml_contract(project_file):
    project = load_project(project_file)

    assert project.version == 1
    assert project.id == "clockwork_owl"
    assert project.title == "The Clockwork Owl"
    assert project.language == "en-US"
    assert project.output.width == 1280
    assert project.output.height == 720
    assert project.output.fps == 24
    assert tuple(project.speakers) == ("narrator", "ada")
    assert project.scenes[0].lines[1].speaker == "ada"


def test_validate_project_accepts_loaded_project(project_file):
    project = load_project(project_file)

    assert validate_project(project) is project


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    [
        (lambda data: data["project"].pop("title"), "project.title"),
        (lambda data: data["speakers"].clear(), "speakers"),
        (lambda data: data["scenes"].clear(), "scenes"),
        (lambda data: data["output"].update({"fps": 0}), "output.fps"),
        (lambda data: data["scenes"][0]["lines"][0].update({"text": ""}), "text"),
    ],
)
def test_load_project_reports_actionable_validation_paths(
    tmp_path, valid_project_data, mutation, expected_path
):
    import yaml

    invalid = deepcopy(valid_project_data)
    mutation(invalid)
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(invalid, sort_keys=False), encoding="utf-8")

    with pytest.raises(ProjectValidationError, match=expected_path):
        load_project(path)


def test_load_project_rejects_duplicate_line_ids(tmp_path, valid_project_data):
    import yaml

    invalid = deepcopy(valid_project_data)
    duplicate = deepcopy(invalid["scenes"][0]["lines"][0])
    invalid["scenes"][0]["lines"].append(duplicate)
    path = tmp_path / "duplicate.yaml"
    path.write_text(yaml.safe_dump(invalid, sort_keys=False), encoding="utf-8")

    with pytest.raises(ProjectValidationError, match="line_001"):
        load_project(path)


def test_load_project_does_not_expand_environment_variables(
    tmp_path, valid_project_data, monkeypatch
):
    """Project text must not accidentally become a secret-expansion surface."""
    import yaml

    monkeypatch.setenv("BOOK_VIDEO_TEST_SECRET", "should-not-appear")
    data = deepcopy(valid_project_data)
    data["scenes"][0]["lines"][0]["text"] = "Say ${BOOK_VIDEO_TEST_SECRET}."
    path = tmp_path / "literal.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    project = load_project(path)

    assert project.scenes[0].lines[0].text == "Say ${BOOK_VIDEO_TEST_SECRET}."


def test_validate_project_assets_fails_before_render(project_file):
    project = load_project(project_file)
    (project_file.parent / "assets" / "workshop.png").unlink()

    with pytest.raises(ProjectValidationError, match=r"image.*workshop\.png"):
        validate_project_assets(project, project_file.parent)
