from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .schema import ProjectSpec


class TimelineError(ValueError):
    """Audio durations cannot form a valid contiguous timeline."""


@dataclass(frozen=True)
class Cue:
    id: str
    scene_id: str
    speaker: str
    text: str
    voice: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class Timeline:
    cues: tuple[Cue, ...]
    duration_ms: int


def build_timeline(
    project: ProjectSpec, *, line_durations_ms: Mapping[str, int]
) -> Timeline:
    lines = [(scene.id, line) for scene in project.scenes for line in scene.lines]
    expected = {line.id for _, line in lines}
    supplied = set(line_durations_ms)
    if supplied != expected:
        missing = sorted(expected - supplied)
        extra = sorted(supplied - expected)
        raise TimelineError(f"duration map mismatch; missing={missing}, extra={extra}")

    for _, line in lines:
        duration = line_durations_ms[line.id]
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise TimelineError(f"duration for {line.id} must be a positive integer")

    fixed_slots = bool(project.scenes and project.scenes[0].duration_ms is not None)
    cursor = 0
    cues: list[Cue] = []
    for scene in project.scenes:
        scene_start = cursor
        for line in scene.lines:
            if line.speaker not in project.speakers:
                raise TimelineError(f"line {line.id} references unknown speaker {line.speaker}")
            duration = line_durations_ms[line.id]
            cues.append(
                Cue(
                    id=line.id,
                    scene_id=scene.id,
                    speaker=line.speaker,
                    text=line.text,
                    voice=project.speakers[line.speaker].voice,
                    start_ms=cursor,
                    end_ms=cursor + duration,
                )
            )
            cursor += duration + line.pause_after_ms
        if fixed_slots:
            assert scene.duration_ms is not None
            slot_end = scene_start + scene.duration_ms
            if cursor > slot_end:
                raise TimelineError(
                    f"scene {scene.id} narration overflow: {cursor - slot_end}ms"
                )
            cursor = slot_end
    if lines and not fixed_slots:
        cursor -= lines[-1][1].pause_after_ms
    return Timeline(cues=tuple(cues), duration_ms=cursor)
