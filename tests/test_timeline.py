from __future__ import annotations

from copy import deepcopy

import pytest

from book_video.schema import load_project
from book_video.timeline import TimelineError, build_timeline


def test_build_timeline_produces_deterministic_line_cues(project_file):
    project = load_project(project_file)

    durations = {"line_001": 1500, "line_002": 1500}
    first = build_timeline(project, line_durations_ms=durations)
    second = build_timeline(project, line_durations_ms=durations)

    assert first == second
    assert [cue.id for cue in first.cues] == ["line_001", "line_002"]
    assert [cue.scene_id for cue in first.cues] == ["workshop", "workshop"]
    assert [cue.speaker for cue in first.cues] == ["narrator", "ada"]
    assert [(cue.start_ms, cue.end_ms) for cue in first.cues] == [
        (0, 1500),
        (1700, 3200),
    ]
    assert [cue.duration_ms for cue in first.cues] == [1500, 1500]
    assert [cue.voice for cue in first.cues] == [
        "en-US-GuyNeural",
        "en-US-JennyNeural",
    ]
    assert first.duration_ms == 3200


def _load_changed_project(tmp_path, valid_project_data, change):
    import yaml

    data = deepcopy(valid_project_data)
    change(data)
    path = tmp_path / "changed.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return load_project(path)


def test_build_timeline_rejects_unknown_speaker(tmp_path, valid_project_data):
    project = _load_changed_project(
        tmp_path,
        valid_project_data,
        lambda data: data["scenes"][0]["lines"][1].update({"speaker": "ghost"}),
    )

    with pytest.raises(TimelineError, match=r"line_002.*ghost|ghost.*line_002"):
        build_timeline(project, line_durations_ms={"line_001": 1500, "line_002": 1500})


@pytest.mark.parametrize(
    "durations",
    [
        {"line_001": 1500},
        {"line_001": 1500, "line_002": 1500, "unknown": 10},
        {"line_001": 1500, "line_002": 0},
    ],
)
def test_build_timeline_rejects_incomplete_or_invalid_duration_maps(
    project_file, durations
):
    project = load_project(project_file)

    with pytest.raises(TimelineError, match="duration"):
        build_timeline(project, line_durations_ms=durations)
