from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import yaml

from .schema import (
    AmbienceSpec,
    LineSpec,
    OutputSpec,
    ProjectSpec,
    SceneSpec,
    SpeakerSpec,
    validate_project,
    validate_project_assets,
)

MODES = ("faithful", "modern")
INTERPRETATION_KINDS = ("explicit", "inferred", "production_choice")
_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SPACE = re.compile(r"\s+")


class AdaptationValidationError(ValueError):
    """An adaptation bundle is malformed or crosses its source boundary."""


@dataclass(frozen=True)
class SourceParagraph:
    id: str
    text: str


@dataclass(frozen=True)
class SourceReference:
    paragraph: str
    quote: str


@dataclass(frozen=True)
class Interpretation:
    kind: str
    detail: str


@dataclass(frozen=True)
class NarrationVariants:
    faithful: str
    modern: str
    pause_after_ms: int = 0


@dataclass(frozen=True)
class AdaptationScene:
    id: str
    title: str
    image: str
    end_image: str
    motion_prompt: str
    duration_ms: int
    source_refs: tuple[SourceReference, ...]
    interpretations: tuple[Interpretation, ...]
    ambience: AmbienceSpec
    narration: NarrationVariants


@dataclass(frozen=True)
class AdaptationPolicy:
    narration_only: bool
    forbid_future_knowledge: bool


@dataclass(frozen=True)
class NarratorSpec:
    id: str
    voice: str
    rate: str
    volume: str
    pitch: str


@dataclass(frozen=True)
class AdaptationSpec:
    version: int
    id: str
    title: str
    language: str
    source_file: str
    source_path: Path
    source_sha256: str
    paragraphs: tuple[SourceParagraph, ...]
    default_mode: str
    target_duration_sec: int
    output: OutputSpec
    narrator: NarratorSpec
    policy: AdaptationPolicy
    scenes: tuple[AdaptationScene, ...]


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise AdaptationValidationError(f"{path} must be an object")
    return value


def _need(mapping: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in mapping:
        raise AdaptationValidationError(f"{path}.{key} is required")
    return mapping[key]


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdaptationValidationError(f"{path} must be non-empty text")
    return value.strip()


def _safe_id(value: Any, path: str) -> str:
    identifier = _text(value, path)
    if not _SAFE_ID.fullmatch(identifier):
        raise AdaptationValidationError(f"{path} must be a safe lowercase identifier")
    return identifier


def _safe_path(value: Any, path: str) -> str:
    relative = _text(value, path).replace("\\", "/")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or ":" in relative or relative.startswith("//"):
        raise AdaptationValidationError(f"{path} must stay inside the adaptation directory")
    return relative


def _integer(value: Any, path: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise AdaptationValidationError(f"{path} must be {minimum}..{maximum}")
    return value


def _number(value: Any, path: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdaptationValidationError(f"{path} must be a number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise AdaptationValidationError(f"{path} must be {minimum:g}..{maximum:g}")
    return result


def _normalized(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def _read_source(root: Path, relative: str) -> tuple[Path, str, tuple[SourceParagraph, ...]]:
    source_path = (root / relative).resolve()
    if not source_path.is_relative_to(root.resolve()):
        raise AdaptationValidationError("adaptation.source_file escapes the project directory")
    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AdaptationValidationError(f"cannot read source file {relative}: {exc}") from exc
    paragraphs = tuple(
        SourceParagraph(id=f"p{index:03}", text=paragraph.strip())
        for index, paragraph in enumerate(
            (part for part in re.split(r"\r?\n\s*\r?\n", source_text) if part.strip()),
            start=1,
        )
    )
    if not paragraphs:
        raise AdaptationValidationError("source file contains no paragraphs")
    return source_path, source_text, paragraphs


def _parse_scene(
    raw: Any,
    *,
    index: int,
    paragraphs: Mapping[str, str],
    narration_only: bool,
) -> AdaptationScene:
    path = f"scenes[{index}]"
    item = _mapping(raw, path)
    scene_id = _safe_id(_need(item, "id", path), f"{path}.id")
    duration_ms = _integer(
        _need(item, "duration_ms", path), f"{path}.duration_ms", minimum=1, maximum=15_000
    )
    source_refs_raw = _need(item, "source_refs", path)
    if not isinstance(source_refs_raw, list) or not source_refs_raw:
        raise AdaptationValidationError(f"{path}.source_refs must not be empty")
    source_refs: list[SourceReference] = []
    for reference_index, raw_reference in enumerate(source_refs_raw):
        reference_path = f"{path}.source_refs[{reference_index}]"
        reference = _mapping(raw_reference, reference_path)
        paragraph_id = _text(
            _need(reference, "paragraph", reference_path), f"{reference_path}.paragraph"
        )
        quote = _text(_need(reference, "quote", reference_path), f"{reference_path}.quote")
        if paragraph_id not in paragraphs:
            raise AdaptationValidationError(f"{reference_path} references unknown {paragraph_id}")
        if _normalized(quote) not in _normalized(paragraphs[paragraph_id]):
            raise AdaptationValidationError(
                f"{reference_path}.quote is not present in {paragraph_id}"
            )
        source_refs.append(SourceReference(paragraph=paragraph_id, quote=quote))

    narration_raw = _mapping(_need(item, "narration", path), f"{path}.narration")
    faithful = _text(
        _need(narration_raw, "faithful", f"{path}.narration"),
        f"{path}.narration.faithful",
    )
    supported_faithful = _normalized(" ".join(reference.quote for reference in source_refs))
    if _normalized(faithful) != supported_faithful:
        raise AdaptationValidationError(
            f"{path}.narration.faithful must contain only the cited source quotes"
        )
    pause_after_ms = _integer(
        narration_raw.get("pause_after_ms", 0),
        f"{path}.narration.pause_after_ms",
        minimum=0,
        maximum=60_000,
    )

    interpretations_raw = item.get("interpretations", [])
    if not isinstance(interpretations_raw, list):
        raise AdaptationValidationError(f"{path}.interpretations must be a list")
    interpretations: list[Interpretation] = []
    for interpretation_index, raw_interpretation in enumerate(interpretations_raw):
        interpretation_path = f"{path}.interpretations[{interpretation_index}]"
        interpretation = _mapping(raw_interpretation, interpretation_path)
        kind = _text(
            _need(interpretation, "kind", interpretation_path),
            f"{interpretation_path}.kind",
        )
        if kind not in INTERPRETATION_KINDS:
            raise AdaptationValidationError(
                f"{interpretation_path}.kind must be one of {INTERPRETATION_KINDS}"
            )
        interpretations.append(
            Interpretation(
                kind=kind,
                detail=_text(
                    _need(interpretation, "detail", interpretation_path),
                    f"{interpretation_path}.detail",
                ),
            )
        )

    ambience_raw = _mapping(_need(item, "ambience", path), f"{path}.ambience")
    motion_prompt = _text(_need(item, "motion_prompt", path), f"{path}.motion_prompt")
    if narration_only:
        lowered = motion_prompt.lower()
        has_closed_mouth = "mouth closed" in lowered or "mouths closed" in lowered
        if not has_closed_mouth or "no visible speech" not in lowered:
            raise AdaptationValidationError(
                f"{path}.motion_prompt must enforce mouth closed and no visible speech"
            )
    return AdaptationScene(
        id=scene_id,
        title=_text(_need(item, "title", path), f"{path}.title"),
        image=_safe_path(_need(item, "image", path), f"{path}.image"),
        end_image=_safe_path(_need(item, "end_image", path), f"{path}.end_image"),
        motion_prompt=motion_prompt,
        duration_ms=duration_ms,
        source_refs=tuple(source_refs),
        interpretations=tuple(interpretations),
        ambience=AmbienceSpec(
            file=_safe_path(
                _need(ambience_raw, "file", f"{path}.ambience"), f"{path}.ambience.file"
            ),
            description=_text(
                _need(ambience_raw, "description", f"{path}.ambience"),
                f"{path}.ambience.description",
            ),
            gain_db=_number(
                ambience_raw.get("gain_db", -24.0),
                f"{path}.ambience.gain_db",
                minimum=-60.0,
                maximum=0.0,
            ),
        ),
        narration=NarrationVariants(
            faithful=faithful,
            modern=_text(
                _need(narration_raw, "modern", f"{path}.narration"),
                f"{path}.narration.modern",
            ),
            pause_after_ms=pause_after_ms,
        ),
    )


def load_adaptation(path: str | Path) -> AdaptationSpec:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AdaptationValidationError(f"cannot read {source}: {exc}") from exc
    root = _mapping(raw, "adaptation file")
    if root.get("version") != 1:
        raise AdaptationValidationError("version must be 1")
    metadata = _mapping(_need(root, "adaptation", "root"), "adaptation")
    source_file = _safe_path(
        _need(metadata, "source_file", "adaptation"), "adaptation.source_file"
    )
    source_path, source_text, paragraph_items = _read_source(source.parent, source_file)
    paragraph_map = {paragraph.id: paragraph.text for paragraph in paragraph_items}
    default_mode = _text(
        _need(metadata, "default_mode", "adaptation"), "adaptation.default_mode"
    )
    if default_mode not in MODES:
        raise AdaptationValidationError(f"adaptation.default_mode must be one of {MODES}")

    output_raw = _mapping(_need(root, "output", "root"), "output")
    narrator_raw = _mapping(_need(root, "narrator", "root"), "narrator")
    policy_raw = _mapping(_need(root, "policy", "root"), "policy")
    narration_only = policy_raw.get("narration_only")
    forbid_future = policy_raw.get("forbid_future_knowledge")
    if not isinstance(narration_only, bool):
        raise AdaptationValidationError("policy.narration_only must be true or false")
    if not isinstance(forbid_future, bool):
        raise AdaptationValidationError("policy.forbid_future_knowledge must be true or false")

    raw_scenes = _need(root, "scenes", "root")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise AdaptationValidationError("scenes must not be empty")
    scenes = tuple(
        _parse_scene(
            item,
            index=index,
            paragraphs=paragraph_map,
            narration_only=narration_only,
        )
        for index, item in enumerate(raw_scenes)
    )
    scene_ids = [scene.id for scene in scenes]
    if len(set(scene_ids)) != len(scene_ids):
        raise AdaptationValidationError("scene ids must be unique")
    target_duration_sec = _integer(
        _need(metadata, "target_duration_sec", "adaptation"),
        "adaptation.target_duration_sec",
        minimum=1,
        maximum=3_600,
    )
    actual_duration_ms = sum(scene.duration_ms for scene in scenes)
    if actual_duration_ms != target_duration_sec * 1_000:
        raise AdaptationValidationError(
            "scene duration total must equal adaptation.target_duration_sec"
        )
    return AdaptationSpec(
        version=1,
        id=_safe_id(_need(metadata, "id", "adaptation"), "adaptation.id"),
        title=_text(_need(metadata, "title", "adaptation"), "adaptation.title"),
        language=_text(
            _need(metadata, "language", "adaptation"), "adaptation.language"
        ),
        source_file=source_file,
        source_path=source_path,
        source_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        paragraphs=paragraph_items,
        default_mode=default_mode,
        target_duration_sec=target_duration_sec,
        output=OutputSpec(
            width=_integer(
                _need(output_raw, "width", "output"), "output.width", minimum=64, maximum=8_192
            ),
            height=_integer(
                _need(output_raw, "height", "output"), "output.height", minimum=64, maximum=8_192
            ),
            fps=_integer(
                _need(output_raw, "fps", "output"), "output.fps", minimum=1, maximum=120
            ),
        ),
        narrator=NarratorSpec(
            id=_safe_id(_need(narrator_raw, "id", "narrator"), "narrator.id"),
            voice=_text(_need(narrator_raw, "voice", "narrator"), "narrator.voice"),
            rate=str(narrator_raw.get("rate", "+0%")),
            volume=str(narrator_raw.get("volume", "+0%")),
            pitch=str(narrator_raw.get("pitch", "+0Hz")),
        ),
        policy=AdaptationPolicy(
            narration_only=narration_only,
            forbid_future_knowledge=forbid_future,
        ),
        scenes=scenes,
    )


def compile_adaptation(adaptation: AdaptationSpec, *, mode: str) -> ProjectSpec:
    if mode not in MODES:
        raise AdaptationValidationError(f"mode must be one of {MODES}")
    project = ProjectSpec(
        version=1,
        id=f"{adaptation.id}_{mode}",
        title=f"{adaptation.title} ({mode})",
        language=adaptation.language,
        output=adaptation.output,
        speakers={
            adaptation.narrator.id: SpeakerSpec(
                voice=adaptation.narrator.voice,
                rate=adaptation.narrator.rate,
                volume=adaptation.narrator.volume,
                pitch=adaptation.narrator.pitch,
            )
        },
        scenes=tuple(
            SceneSpec(
                id=scene.id,
                title=scene.title,
                image=scene.image,
                end_image=scene.end_image,
                motion_prompt=scene.motion_prompt,
                duration_ms=scene.duration_ms,
                ambience=scene.ambience,
                lines=(
                    LineSpec(
                        id=f"{scene.id}_{mode}",
                        speaker=adaptation.narrator.id,
                        text=getattr(scene.narration, mode),
                        pause_after_ms=scene.narration.pause_after_ms,
                    ),
                ),
            )
            for scene in adaptation.scenes
        ),
    )
    return validate_project(project)


def _project_dict(project: ProjectSpec) -> dict[str, Any]:
    return {
        "version": project.version,
        "project": {
            "id": project.id,
            "title": project.title,
            "language": project.language,
        },
        "output": {
            "width": project.output.width,
            "height": project.output.height,
            "fps": project.output.fps,
        },
        "speakers": {
            speaker_id: {
                "voice": speaker.voice,
                "rate": speaker.rate,
                "volume": speaker.volume,
                "pitch": speaker.pitch,
            }
            for speaker_id, speaker in project.speakers.items()
        },
        "scenes": [
            {
                "id": scene.id,
                "title": scene.title,
                "image": scene.image,
                "end_image": scene.end_image,
                "motion_prompt": scene.motion_prompt,
                "duration_ms": scene.duration_ms,
                "ambience": {
                    "file": scene.ambience.file,
                    "description": scene.ambience.description,
                    "gain_db": scene.ambience.gain_db,
                }
                if scene.ambience
                else None,
                "lines": [
                    {
                        "id": line.id,
                        "speaker": line.speaker,
                        "text": line.text,
                        "pause_after_ms": line.pause_after_ms,
                    }
                    for line in scene.lines
                ],
            }
            for scene in project.scenes
        ],
    }


def write_adaptation_variants(
    adaptation: AdaptationSpec, *, output_dir: str | Path
) -> dict[str, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    source_root = adaptation.source_path.parent.resolve()
    for relative in {
        item
        for scene in adaptation.scenes
        for item in (scene.image, scene.end_image, scene.ambience.file)
    }:
        source_asset = (source_root / relative).resolve()
        if (
            not source_asset.is_relative_to(source_root)
            or source_asset.is_symlink()
            or not source_asset.is_file()
        ):
            raise AdaptationValidationError(f"adaptation asset is missing or unsafe: {relative}")
        destination_asset = (destination / relative).resolve()
        if not destination_asset.is_relative_to(destination.resolve()):
            raise AdaptationValidationError(f"adaptation asset path is unsafe: {relative}")
        if source_asset != destination_asset:
            destination_asset.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_asset, destination_asset)
    artifacts: dict[str, Path] = {}
    for mode in MODES:
        project = compile_adaptation(adaptation, mode=mode)
        validate_project_assets(project, destination)
        path = destination / f"project.{mode}.yaml"
        path.write_text(
            yaml.safe_dump(_project_dict(project), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        artifacts[mode] = path

    provenance = {
        "version": 1,
        "adaptation_id": adaptation.id,
        "source": {
            "file": adaptation.source_file,
            "sha256": adaptation.source_sha256,
            "included_in_colab_package": False,
        },
        "policy": {
            "narration_only": adaptation.policy.narration_only,
            "forbid_future_knowledge": adaptation.policy.forbid_future_knowledge,
        },
        "scenes": [
            {
                "id": scene.id,
                "source_refs": [
                    {"paragraph": reference.paragraph, "quote": reference.quote}
                    for reference in scene.source_refs
                ],
                "interpretations": [
                    {"kind": item.kind, "detail": item.detail}
                    for item in scene.interpretations
                ],
            }
            for scene in adaptation.scenes
        ],
    }
    (destination / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    ambience_plan = {
        "version": 1,
        "music": False,
        "scenes": [
            {
                "id": scene.id,
                "file": scene.ambience.file,
                "description": scene.ambience.description,
                "gain_db": scene.ambience.gain_db,
                "duration_ms": scene.duration_ms,
            }
            for scene in adaptation.scenes
        ],
    }
    (destination / "ambience-plan.json").write_text(
        json.dumps(ambience_plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return artifacts
