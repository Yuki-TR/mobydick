from __future__ import annotations

import os
from pathlib import Path

from .schema import ProjectSpec, validate_project_assets
from .timeline import Timeline


class UpstreamSpecError(ValueError):
    """The prepared project cannot be represented by drama-video."""


def build_drama_spec(
    *,
    project: ProjectSpec,
    timeline: Timeline,
    master_audio: str | Path,
    cues_file: str | Path,
    project_root: str | Path,
    spec_root: str | Path,
) -> dict:
    root = Path(project_root).resolve()
    output_root = Path(spec_root).resolve()
    validate_project_assets(project, root)

    def portable(path: str | Path) -> str:
        return os.path.relpath(Path(path).resolve(), output_root).replace("\\", "/")

    cue_by_id = {cue.id: cue for cue in timeline.cues}
    shots: list[dict] = []
    for scene in project.scenes:
        scene_cues = [cue_by_id[line.id] for line in scene.lines]
        start_ms = scene_cues[0].start_ms
        end_ms = scene_cues[-1].end_ms + scene.lines[-1].pause_after_ms
        if scene is project.scenes[-1]:
            end_ms = timeline.duration_ms
        duration_sec = round((end_ms - start_ms) / 1000, 3)
        if duration_sec > 15:
            raise UpstreamSpecError(
                f"scene {scene.id} is {duration_sec}s; drama-video shots are limited to 15s"
            )
        shots.append(
            {
                "label": scene.id,
                "image": portable(root / scene.image),
                "prompt": scene.motion_prompt,
                "start_sec": round(start_ms / 1000, 3),
                "duration_sec": duration_sec,
            }
        )
    return {
        "title": project.title,
        "video": {
            "resolution": [project.output.width, project.output.height],
            "fps": project.output.fps,
            "tail_buffer_sec": 0.0,
        },
        "audio": {
            "file": portable(master_audio),
            "cues": portable(cues_file),
        },
        "shots": shots,
    }
