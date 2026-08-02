from __future__ import annotations

from book_video.schema import load_project
from book_video.timeline import build_timeline
from book_video.upstream import build_drama_spec


def test_build_drama_spec_maps_project_timeline_audio_and_images(project_file, tmp_path):
    project = load_project(project_file)
    timeline = build_timeline(
        project, line_durations_ms={"line_001": 1500, "line_002": 1500}
    )
    master_audio = tmp_path / "audio" / "master.mp3"
    cues_file = tmp_path / "audio" / "cues.json"

    spec = build_drama_spec(
        project=project,
        timeline=timeline,
        master_audio=master_audio,
        cues_file=cues_file,
        project_root=project_file.parent,
        spec_root=tmp_path,
    )

    assert spec == {
        "title": "The Clockwork Owl",
        "video": {
            "resolution": [1280, 720],
            "fps": 24,
            "tail_buffer_sec": 0.0,
        },
        "audio": {
            "file": "audio/master.mp3",
            "cues": "audio/cues.json",
        },
        "shots": [
            {
                "label": "workshop",
                "image": "assets/workshop.png",
                "prompt": "A slow push toward the workbench.",
                "start_sec": 0.0,
                "duration_sec": 3.2,
            }
        ],
    }


def test_build_drama_spec_is_stable_across_repeated_calls(project_file, tmp_path):
    project = load_project(project_file)
    timeline = build_timeline(
        project, line_durations_ms={"line_001": 1500, "line_002": 1500}
    )
    kwargs = {
        "project": project,
        "timeline": timeline,
        "master_audio": tmp_path / "master.mp3",
        "cues_file": tmp_path / "cues.json",
        "project_root": project_file.parent,
        "spec_root": tmp_path,
    }

    assert build_drama_spec(**kwargs) == build_drama_spec(**kwargs)


def test_build_drama_spec_uses_fixed_visual_slots(tmp_path, valid_project_data):
    import yaml

    valid_project_data["scenes"][0]["duration_ms"] = 5000
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "workshop.png").write_bytes(b"image")
    project_path = tmp_path / "project.yaml"
    project_path.write_text(
        yaml.safe_dump(valid_project_data, sort_keys=False), encoding="utf-8"
    )
    project = load_project(project_path)
    timeline = build_timeline(
        project, line_durations_ms={"line_001": 1500, "line_002": 1500}
    )

    spec = build_drama_spec(
        project=project,
        timeline=timeline,
        master_audio=tmp_path / "master.mp3",
        cues_file=tmp_path / "cues.json",
        project_root=tmp_path,
        spec_root=tmp_path,
    )

    assert spec["shots"] == [
        {
            "label": "workshop",
            "image": "assets/workshop.png",
            "prompt": "A slow push toward the workbench.",
            "start_sec": 0.0,
            "duration_sec": 5.0,
        }
    ]


def test_build_drama_spec_passes_first_and_last_frame_to_upstream(
    tmp_path, valid_project_data
):
    import yaml

    valid_project_data["scenes"][0]["end_image"] = "assets/workshop-end.png"
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "workshop.png").write_bytes(b"first")
    (assets / "workshop-end.png").write_bytes(b"last")
    project_path = tmp_path / "project.yaml"
    project_path.write_text(
        yaml.safe_dump(valid_project_data, sort_keys=False), encoding="utf-8"
    )
    project = load_project(project_path)
    timeline = build_timeline(
        project, line_durations_ms={"line_001": 1500, "line_002": 1500}
    )

    spec = build_drama_spec(
        project=project,
        timeline=timeline,
        master_audio=tmp_path / "master.mp3",
        cues_file=tmp_path / "cues.json",
        project_root=tmp_path,
        spec_root=tmp_path,
    )

    assert spec["shots"][0]["image"] == "assets/workshop.png"
    assert spec["shots"][0]["last_image"] == "assets/workshop-end.png"
