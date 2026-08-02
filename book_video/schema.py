from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import yaml

_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ProjectValidationError(ValueError):
    """A project file is malformed or unsafe."""


@dataclass(frozen=True)
class OutputSpec:
    width: int
    height: int
    fps: int


@dataclass(frozen=True)
class SpeakerSpec:
    voice: str
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"


@dataclass(frozen=True)
class LineSpec:
    id: str
    speaker: str
    text: str
    pause_after_ms: int = 0


@dataclass(frozen=True)
class AmbienceSpec:
    file: str
    description: str
    gain_db: float = -24.0


@dataclass(frozen=True)
class SceneSpec:
    id: str
    title: str
    image: str
    end_image: str | None
    motion_prompt: str
    lines: tuple[LineSpec, ...]
    duration_ms: int | None = None
    ambience: AmbienceSpec | None = None


@dataclass(frozen=True)
class ProjectSpec:
    version: int
    id: str
    title: str
    language: str
    output: OutputSpec
    speakers: Mapping[str, SpeakerSpec]
    scenes: tuple[SceneSpec, ...]


def _need(mapping: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in mapping:
        raise ProjectValidationError(f"{path}.{key} is required")
    return mapping[key]


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ProjectValidationError(f"{path} must be an object")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectValidationError(f"{path} must be non-empty text")
    return value


def _safe_id(value: Any, path: str) -> str:
    text = _text(value, path)
    if not _SAFE_ID.fullmatch(text):
        raise ProjectValidationError(
            f"{path} must match {_SAFE_ID.pattern!r}; unsafe line/scene ids are rejected"
        )
    return text


def _asset_path(value: Any, path: str) -> str:
    text = _text(value, path).replace("\\", "/")
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts or ":" in text or text.startswith("//"):
        raise ProjectValidationError(f"{path} must stay inside the project directory")
    return text


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProjectValidationError(f"{path} must be a positive integer")
    return value


def _scene_duration(value: Any, path: str) -> int:
    duration = _positive_int(value, path)
    if duration > 15_000:
        raise ProjectValidationError(f"{path} must be 1..15000")
    return duration


def project_from_dict(raw: Mapping[str, Any]) -> ProjectSpec:
    root = _mapping(raw, "project file")
    version = _need(root, "version", "root")
    if version != 1:
        raise ProjectValidationError("version must be 1")

    project = _mapping(_need(root, "project", "root"), "project")
    output = _mapping(_need(root, "output", "root"), "output")
    raw_speakers = _mapping(_need(root, "speakers", "root"), "speakers")
    if not raw_speakers:
        raise ProjectValidationError("speakers must define at least one voice")

    speakers: dict[str, SpeakerSpec] = {}
    for speaker_id, value in raw_speakers.items():
        safe_speaker_id = _safe_id(speaker_id, f"speakers.{speaker_id}")
        item = _mapping(value, f"speakers.{speaker_id}")
        speakers[safe_speaker_id] = SpeakerSpec(
            voice=_text(_need(item, "voice", f"speakers.{speaker_id}"), f"speakers.{speaker_id}.voice"),
            rate=str(item.get("rate", "+0%")),
            volume=str(item.get("volume", "+0%")),
            pitch=str(item.get("pitch", "+0Hz")),
        )

    raw_scenes = _need(root, "scenes", "root")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ProjectValidationError("scenes must contain at least one scene")

    scene_ids: set[str] = set()
    line_ids: set[str] = set()
    scenes: list[SceneSpec] = []
    fixed_duration_count = 0
    for scene_index, raw_scene in enumerate(raw_scenes):
        path = f"scenes[{scene_index}]"
        item = _mapping(raw_scene, path)
        scene_id = _safe_id(_need(item, "id", path), f"{path}.id")
        if scene_id in scene_ids:
            raise ProjectValidationError(f"duplicate scene id: {scene_id}")
        scene_ids.add(scene_id)
        raw_lines = _need(item, "lines", path)
        if not isinstance(raw_lines, list) or not raw_lines:
            raise ProjectValidationError(f"{path}.lines must not be empty")
        lines: list[LineSpec] = []
        for line_index, raw_line in enumerate(raw_lines):
            line_path = f"{path}.lines[{line_index}]"
            line = _mapping(raw_line, line_path)
            line_id = _safe_id(_need(line, "id", line_path), f"{line_path}.id")
            if line_id in line_ids:
                raise ProjectValidationError(f"duplicate line id: {line_id}")
            line_ids.add(line_id)
            pause = line.get("pause_after_ms", 0)
            if isinstance(pause, bool) or not isinstance(pause, int) or pause < 0 or pause > 60_000:
                raise ProjectValidationError(f"{line_path}.pause_after_ms must be 0..60000")
            lines.append(
                LineSpec(
                    id=line_id,
                    speaker=_safe_id(_need(line, "speaker", line_path), f"{line_path}.speaker"),
                    text=_text(_need(line, "text", line_path), f"{line_path}.text"),
                    pause_after_ms=pause,
                )
            )
        duration_ms = item.get("duration_ms")
        if duration_ms is not None:
            duration_ms = _scene_duration(duration_ms, f"{path}.duration_ms")
            fixed_duration_count += 1
        ambience = None
        if item.get("ambience") is not None:
            raw_ambience = _mapping(item["ambience"], f"{path}.ambience")
            raw_gain = raw_ambience.get("gain_db", -24.0)
            if isinstance(raw_gain, bool) or not isinstance(raw_gain, (int, float)):
                raise ProjectValidationError(f"{path}.ambience.gain_db must be a number")
            gain_db = float(raw_gain)
            if gain_db < -60.0 or gain_db > 0.0:
                raise ProjectValidationError(f"{path}.ambience.gain_db must be -60..0")
            ambience = AmbienceSpec(
                file=_asset_path(
                    _need(raw_ambience, "file", f"{path}.ambience"),
                    f"{path}.ambience.file",
                ),
                description=_text(
                    _need(raw_ambience, "description", f"{path}.ambience"),
                    f"{path}.ambience.description",
                ),
                gain_db=gain_db,
            )
        scenes.append(
            SceneSpec(
                id=scene_id,
                title=_text(_need(item, "title", path), f"{path}.title"),
                image=_asset_path(_need(item, "image", path), f"{path}.image"),
                end_image=(
                    _asset_path(item["end_image"], f"{path}.end_image")
                    if item.get("end_image") is not None
                    else None
                ),
                motion_prompt=_text(_need(item, "motion_prompt", path), f"{path}.motion_prompt"),
                lines=tuple(lines),
                duration_ms=duration_ms,
                ambience=ambience,
            )
        )

    if fixed_duration_count not in (0, len(scenes)):
        raise ProjectValidationError(
            "scenes must either all define duration_ms or all use measured timing"
        )

    spec = ProjectSpec(
        version=version,
        id=_safe_id(_need(project, "id", "project"), "project.id"),
        title=_text(_need(project, "title", "project"), "project.title"),
        language=_text(_need(project, "language", "project"), "project.language"),
        output=OutputSpec(
            width=_positive_int(_need(output, "width", "output"), "output.width"),
            height=_positive_int(_need(output, "height", "output"), "output.height"),
            fps=_positive_int(_need(output, "fps", "output"), "output.fps"),
        ),
        speakers=speakers,
        scenes=tuple(scenes),
    )
    return spec


def validate_project(project: ProjectSpec) -> ProjectSpec:
    unknown = [
        (line.id, line.speaker)
        for scene in project.scenes
        for line in scene.lines
        if line.speaker not in project.speakers
    ]
    if unknown:
        line_id, speaker = unknown[0]
        raise ProjectValidationError(f"line {line_id} references unknown speaker {speaker}")
    return project


def validate_project_assets(project: ProjectSpec, project_root: str | Path) -> ProjectSpec:
    root = Path(project_root).resolve()
    image_paths = [scene.image for scene in project.scenes]
    image_paths.extend(scene.end_image for scene in project.scenes if scene.end_image)
    missing_images = [image for image in image_paths if not (root / image).is_file()]
    if missing_images:
        raise ProjectValidationError(f"scene image is missing: {missing_images[0]}")
    missing_ambience = [
        scene.ambience.file
        for scene in project.scenes
        if scene.ambience is not None and not (root / scene.ambience.file).is_file()
    ]
    if missing_ambience:
        raise ProjectValidationError(f"scene ambience is missing: {missing_ambience[0]}")
    return project


def load_project(path: str | Path) -> ProjectSpec:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
        raw = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ProjectValidationError(f"cannot read {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProjectValidationError("project file root must be an object")
    return project_from_dict(raw)
