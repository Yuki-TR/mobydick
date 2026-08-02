from __future__ import annotations

import json
from dataclasses import dataclass
import book_video.edge_audio as edge_audio
from book_video.edge_audio import EdgeAudioRenderer, _pause_gaps
from book_video.schema import load_project


@dataclass(frozen=True)
class FakeSynthesis:
    audio: bytes
    duration_ms: int


class RecordingBackend:
    """Pure in-memory Edge-compatible backend; a network call is always a bug."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def synthesize(
        self, *, text: str, voice: str, rate: str, volume: str, pitch: str
    ) -> FakeSynthesis:
        self.calls.append((text, voice, rate, volume, pitch))
        return FakeSynthesis(audio=f"AUDIO:{voice}:{text}".encode(), duration_ms=1500)


def test_renderer_uses_injected_backend_and_writes_portable_artifacts(
    tmp_path, project_file
):
    project = load_project(project_file)
    backend = RecordingBackend()

    artifacts = EdgeAudioRenderer(backend=backend).render(
        project=project,
        output_dir=tmp_path / "audio",
    )

    assert backend.calls == [
        ("The workshop woke before dawn.", "en-US-GuyNeural", "+0%", "+0%", "+0Hz"),
        ("Today, you will fly.", "en-US-JennyNeural", "+0%", "+0%", "+0Hz"),
    ]
    assert artifacts.manifest_path == tmp_path / "audio" / "manifest.json"
    assert artifacts.cues_path == tmp_path / "audio" / "cues.json"
    assert artifacts.subtitle_path == tmp_path / "audio" / "subtitles.srt"
    assert artifacts.manifest_path.is_file()
    assert artifacts.cues_path.is_file()
    assert artifacts.subtitle_path.is_file()
    assert artifacts.master_audio_path.is_file()
    assert [(cue.start_ms, cue.end_ms) for cue in artifacts.timeline.cues] == [
        (0, 1500),
        (1700, 3200),
    ]


def test_renderer_manifest_and_cues_are_deterministic_json(tmp_path, project_file):
    project = load_project(project_file)
    artifacts = EdgeAudioRenderer(backend=RecordingBackend()).render(
        project=project,
        output_dir=tmp_path / "audio",
    )

    manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    cues = json.loads(artifacts.cues_path.read_text(encoding="utf-8"))

    assert manifest == {
        "version": 1,
        "project_id": "clockwork_owl",
        "duration_ms": 3200,
        "master_audio": "master.mp3",
        "clips": [
            {
                "id": "line_001",
                "file": "clips/line_001.mp3",
                "duration_ms": 1500,
                "sha256": manifest["clips"][0]["sha256"],
            },
            {
                "id": "line_002",
                "file": "clips/line_002.mp3",
                "duration_ms": 1500,
                "sha256": manifest["clips"][1]["sha256"],
            },
        ],
    }
    assert all(len(clip["sha256"]) == 64 for clip in manifest["clips"])
    assert cues == {
        "version": 1,
        "duration_sec": 3.2,
        "cues": [
            {
                "id": "line_001",
                "kind": "line",
                "scene_id": "workshop",
                "speaker": "narrator",
                "text": "The workshop woke before dawn.",
                "start": 0.0,
                "end": 1.5,
            },
            {
                "id": "line_002",
                "kind": "line",
                "scene_id": "workshop",
                "speaker": "ada",
                "text": "Today, you will fly.",
                "start": 1.7,
                "end": 3.2,
            },
        ],
    }


def test_renderer_writes_valid_srt_timestamps(tmp_path, project_file):
    project = load_project(project_file)
    artifacts = EdgeAudioRenderer(backend=RecordingBackend()).render(
        project=project,
        output_dir=tmp_path / "audio",
    )

    assert artifacts.subtitle_path.read_text(encoding="utf-8") == (
        "1\n"
        "00:00:00,000 --> 00:00:01,500\n"
        "The workshop woke before dawn.\n\n"
        "2\n"
        "00:00:01,700 --> 00:00:03,200\n"
        "Today, you will fly.\n"
    )


def test_renderer_never_places_user_ids_outside_output_directory(
    tmp_path, valid_project_data
):
    import pytest
    import yaml

    valid_project_data["scenes"][0]["lines"][0]["id"] = "../../escape"
    path = tmp_path / "unsafe.yaml"
    path.write_text(yaml.safe_dump(valid_project_data, sort_keys=False), encoding="utf-8")

    from book_video.schema import ProjectValidationError

    with pytest.raises(ProjectValidationError, match="line"):
        load_project(path)
    assert not (tmp_path / "escape.mp3").exists()


def test_fixed_timeline_padding_fills_the_shared_visual_slot(
    tmp_path, valid_project_data
):
    import yaml

    valid_project_data["scenes"][0]["duration_ms"] = 5000
    path = tmp_path / "project.yaml"
    path.write_text(yaml.safe_dump(valid_project_data, sort_keys=False), encoding="utf-8")
    project = load_project(path)
    timeline = edge_audio.build_timeline(
        project, line_durations_ms={"line_001": 1500, "line_002": 1500}
    )

    assert _pause_gaps(timeline) == [200, 1800]


def test_renderer_mixes_scene_ambience_under_brian_narration(
    tmp_path, valid_project_data, monkeypatch
):
    import yaml

    valid_project_data["speakers"] = {
        "narrator": {"voice": "en-US-BrianMultilingualNeural"}
    }
    valid_project_data["scenes"][0]["lines"] = [
        {
            "id": "line_001",
            "speaker": "narrator",
            "text": "Call me Ishmael.",
            "pause_after_ms": 0,
        }
    ]
    valid_project_data["scenes"][0].update(
        {
            "duration_ms": 5000,
            "ambience": {
                "file": "assets/harbor.mp3",
                "description": "Distant harbor water.",
                "gain_db": -24,
            },
        }
    )
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "harbor.mp3").write_bytes(b"ambience")
    path = tmp_path / "project.yaml"
    path.write_text(yaml.safe_dump(valid_project_data, sort_keys=False), encoding="utf-8")
    project = load_project(path)
    calls = []

    def fake_mix(*, narration, output, project, timeline, project_root):
        calls.append((narration, output, project, timeline, project_root))
        output.write_bytes(b"mixed")

    monkeypatch.setattr(edge_audio, "_mix_ambience", fake_mix)

    artifacts = EdgeAudioRenderer(backend=RecordingBackend()).render(
        project=project,
        output_dir=tmp_path / "audio",
        project_root=tmp_path,
    )

    assert artifacts.master_audio_path.read_bytes() == b"mixed"
    assert len(calls) == 1
    assert calls[0][3].duration_ms == 5000
    assert calls[0][4] == tmp_path


def test_failed_prepare_does_not_leave_a_stale_master_audio(
    tmp_path, valid_project_data
):
    import pytest
    import yaml

    valid_project_data["scenes"][0]["duration_ms"] = 1000
    project_path = tmp_path / "project.yaml"
    project_path.write_text(
        yaml.safe_dump(valid_project_data, sort_keys=False), encoding="utf-8"
    )
    output = tmp_path / "audio"
    output.mkdir()
    stale_master = output / "master.mp3"
    stale_master.write_bytes(b"stale-success")

    with pytest.raises(ValueError, match="overflow"):
        EdgeAudioRenderer(backend=RecordingBackend()).render(
            project=load_project(project_path), output_dir=output
        )

    assert not stale_master.exists()
