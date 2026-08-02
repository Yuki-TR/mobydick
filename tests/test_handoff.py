from __future__ import annotations

import json
import zipfile

import yaml

from book_video.adaptation import load_adaptation
from book_video.handoff import build_mux_command, write_handoff_bundle


def _adaptation_file(tmp_path):
    tmp_path.mkdir(parents=True)
    (tmp_path / "source.txt").write_text("Call me Ishmael.\n", encoding="utf-8")
    assets = tmp_path / "assets"
    (assets / "ambience").mkdir(parents=True)
    (assets / "first.png").write_bytes(b"first")
    (assets / "last.png").write_bytes(b"last")
    (assets / "ambience" / "sea.wav").write_bytes(b"sea")
    data = {
        "version": 1,
        "adaptation": {
            "id": "loomings",
            "title": "Loomings",
            "language": "en-US",
            "source_file": "source.txt",
            "default_mode": "faithful",
            "target_duration_sec": 5,
        },
        "output": {"width": 1920, "height": 1080, "fps": 24},
        "narrator": {"id": "ishmael", "voice": "en-US-BrianMultilingualNeural"},
        "policy": {"narration_only": True, "forbid_future_knowledge": True},
        "scenes": [
            {
                "id": "opening",
                "title": "Opening",
                "image": "assets/first.png",
                "end_image": "assets/last.png",
                "duration_ms": 5000,
                "motion_prompt": "Ishmael turns, mouth closed, no visible speech.",
                "source_refs": [{"paragraph": "p001", "quote": "Call me Ishmael."}],
                "interpretations": [],
                "ambience": {
                    "description": "Sea",
                    "file": "assets/ambience/sea.wav",
                    "gain_db": -24,
                },
                "narration": {
                    "faithful": "Call me Ishmael.",
                    "modern": "You can call me Ishmael.",
                },
            }
        ],
    }
    path = tmp_path / "adaptation.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _fake_audio_build(root, mode):
    audio = root / mode / "audio"
    audio.mkdir(parents=True)
    for name in ("master.mp3", "cues.json", "subtitles.srt", "manifest.json"):
        (audio / name).write_bytes(f"{mode}:{name}".encode())
    return root / mode


def test_handoff_bundle_contains_one_render_plan_and_two_audio_variants(tmp_path):
    adaptation = load_adaptation(_adaptation_file(tmp_path / "source"))
    faithful = _fake_audio_build(tmp_path / "prepared", "faithful")
    modern = _fake_audio_build(tmp_path / "prepared", "modern")
    output = tmp_path / "handoff"
    output.mkdir()
    (output / "source.txt").write_text("stale private source", encoding="utf-8")
    archive = tmp_path / "handoff.zip"

    write_handoff_bundle(
        adaptation,
        prepared_builds={"faithful": faithful, "modern": modern},
        output_dir=output,
        archive_path=archive,
    )

    spec = yaml.safe_load((output / "render_spec.yaml").read_text("utf-8"))
    handoff = json.loads((output / "handoff.json").read_text("utf-8"))
    assert spec["audio"]["file"] == "variants/faithful/audio/master.mp3"
    assert spec["shots"][0]["image"] == "assets/first.png"
    assert spec["shots"][0]["last_image"] == "assets/last.png"
    assert handoff["canonical_render_variant"] == "faithful"
    assert set(handoff["variants"]) == {"faithful", "modern"}
    assert (output / "source.txt").is_file()
    assert (output / "checksums.sha256").is_file()
    with zipfile.ZipFile(archive) as bundle:
        assert "render_spec.yaml" in bundle.namelist()
        assert "assets/last.png" in bundle.namelist()
        assert all("source.txt" not in name for name in bundle.namelist())


def test_modern_mux_command_reuses_video_stream_and_replaces_audio(tmp_path):
    command = build_mux_command(
        ffmpeg="ffmpeg",
        video=tmp_path / "final.mp4",
        audio=tmp_path / "modern.mp3",
        subtitles=tmp_path / "modern.srt",
        output=tmp_path / "final-modern.mp4",
    )

    assert command[:6] == [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
    ]
    assert "copy" in command
    assert "aac" in command
    assert "mov_text" in command
