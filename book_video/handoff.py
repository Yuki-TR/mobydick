from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Mapping

import yaml

from .adaptation import AdaptationSpec, MODES, write_adaptation_variants


class HandoffError(ValueError):
    """A prepared adaptation cannot be packaged or muxed safely."""


def _copy_audio_build(source: Path, destination: Path, *, mode: str) -> tuple[Path, ...]:
    audio_source = source / "audio"
    required = ("master.mp3", "cues.json", "subtitles.srt", "manifest.json")
    missing = [name for name in required if not (audio_source / name).is_file()]
    if missing:
        raise HandoffError(f"{mode} prepared build is missing audio/{missing[0]}")
    shutil.copytree(audio_source, destination / "audio", dirs_exist_ok=True)
    return tuple(path for path in (destination / "audio").rglob("*") if path.is_file())


def _render_spec(adaptation: AdaptationSpec) -> dict:
    start_ms = 0
    shots: list[dict] = []
    for scene in adaptation.scenes:
        shots.append(
            {
                "label": scene.id,
                "image": scene.image,
                "last_image": scene.end_image,
                "prompt": scene.motion_prompt,
                "start_sec": round(start_ms / 1000, 3),
                "duration_sec": round(scene.duration_ms / 1000, 3),
            }
        )
        start_ms += scene.duration_ms
    return {
        "title": adaptation.title,
        "video": {
            "resolution": [adaptation.output.width, adaptation.output.height],
            "fps": adaptation.output.fps,
            "tail_buffer_sec": 0.0,
        },
        "audio": {
            "file": "variants/faithful/audio/master.mp3",
            "cues": "variants/faithful/audio/cues.json",
        },
        "shots": shots,
    }


def _write_zip(source: Path, files: tuple[Path, ...], archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(files)):
            if path.is_symlink():
                raise HandoffError(f"refusing to package symlink: {path}")
            bundle.write(path, path.relative_to(source).as_posix())


def write_handoff_bundle(
    adaptation: AdaptationSpec,
    *,
    prepared_builds: Mapping[str, str | Path],
    output_dir: str | Path,
    archive_path: str | Path | None = None,
) -> Path:
    if set(prepared_builds) != set(MODES):
        raise HandoffError(f"prepared_builds must contain exactly {MODES}")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    write_adaptation_variants(adaptation, output_dir=destination)
    bundle_files = [
        destination / "project.faithful.yaml",
        destination / "project.modern.yaml",
        destination / "provenance.json",
        destination / "ambience-plan.json",
    ]
    bundle_files.extend(
        destination / relative
        for scene in adaptation.scenes
        for relative in (scene.image, scene.end_image, scene.ambience.file)
    )
    for mode in MODES:
        bundle_files.extend(
            _copy_audio_build(
                Path(prepared_builds[mode]), destination / "variants" / mode, mode=mode
            )
        )

    spec_path = destination / "render_spec.yaml"
    spec_path.write_text(
        yaml.safe_dump(_render_spec(adaptation), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    bundle_files.append(spec_path)
    handoff = {
        "version": 1,
        "adaptation_id": adaptation.id,
        "canonical_render_variant": "faithful",
        "render_spec": "render_spec.yaml",
        "duration_sec": adaptation.target_duration_sec,
        "variants": {
            "faithful": {
                "audio": "variants/faithful/audio/master.mp3",
                "subtitles": "variants/faithful/audio/subtitles.srt",
                "output": "final.mp4",
            },
            "modern": {
                "audio": "variants/modern/audio/master.mp3",
                "subtitles": "variants/modern/audio/subtitles.srt",
                "output": "final-modern.mp4",
            },
        },
        "colab_stages": ["preflight", "plan", "shot 1", "shots", "assemble", "mux modern"],
        "source_text_included": False,
    }
    handoff_path = destination / "handoff.json"
    handoff_path.write_text(
        json.dumps(handoff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    bundle_files.append(handoff_path)
    checksums_path = destination / "checksums.sha256"
    checksums_path.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
            f"{path.relative_to(destination).as_posix()}\n"
            for path in sorted(set(bundle_files))
        ),
        encoding="utf-8",
    )
    bundle_files.append(checksums_path)
    if archive_path is not None:
        _write_zip(destination, tuple(bundle_files), Path(archive_path))
    return spec_path


def build_mux_command(
    *,
    ffmpeg: str,
    video: str | Path,
    audio: str | Path,
    output: str | Path,
    subtitles: str | Path | None = None,
) -> list[str]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
    ]
    if subtitles is not None:
        command.extend(["-i", str(subtitles)])
    command.extend(["-map", "0:v:0", "-map", "1:a:0"])
    if subtitles is not None:
        command.extend(["-map", "2:0", "-c:s", "mov_text"])
    command.extend(
        ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output)]
    )
    return command


def mux_variant(
    *,
    ffmpeg: str,
    video: str | Path,
    audio: str | Path,
    output: str | Path,
    subtitles: str | Path | None = None,
) -> Path:
    video_path = Path(video)
    audio_path = Path(audio)
    subtitle_path = Path(subtitles) if subtitles is not None else None
    for label, path in (("video", video_path), ("audio", audio_path)):
        if not path.is_file():
            raise HandoffError(f"{label} is missing: {path}")
    if subtitle_path is not None and not subtitle_path.is_file():
        raise HandoffError(f"subtitles are missing: {subtitle_path}")
    output_path = Path(output)
    resolved_output = output_path.resolve()
    protected_inputs = {video_path.resolve(), audio_path.resolve()}
    if subtitle_path is not None:
        protected_inputs.add(subtitle_path.resolve())
    if resolved_output in protected_inputs:
        raise HandoffError("mux output must not overwrite an input file")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        build_mux_command(
            ffmpeg=ffmpeg,
            video=video_path,
            audio=audio_path,
            subtitles=subtitle_path,
            output=output_path,
        ),
        check=True,
    )
    return output_path
