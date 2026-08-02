from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .schema import ProjectSpec, validate_project
from .timeline import Timeline, build_timeline


class SynthesisResult(Protocol):
    audio: bytes
    duration_ms: int


class SynthesisBackend(Protocol):
    def synthesize(
        self,
        *,
        text: str,
        voice: str,
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ) -> SynthesisResult: ...


@dataclass(frozen=True)
class EdgeSynthesis:
    audio: bytes
    duration_ms: int


class EdgeTTSBackend:
    """Synchronous adapter around rany2/edge-tts's async streaming API."""

    audio_format = "mp3"

    def __init__(self, *, rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz"):
        self.rate = rate
        self.volume = volume
        self.pitch = pitch

    def synthesize(
        self,
        *,
        text: str,
        voice: str,
        rate: str | None = None,
        volume: str | None = None,
        pitch: str | None = None,
    ) -> EdgeSynthesis:
        return asyncio.run(
            self._synthesize(
                text=text,
                voice=voice,
                rate=rate or self.rate,
                volume=volume or self.volume,
                pitch=pitch or self.pitch,
            )
        )

    async def _synthesize(
        self, *, text: str, voice: str, rate: str, volume: str, pitch: str
    ) -> EdgeSynthesis:
        try:
            import edge_tts
        except ImportError as exc:  # pragma: no cover - packaging/runtime guard
            raise RuntimeError("edge-tts is not installed; run pip install -e .") from exc
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            volume=volume,
            pitch=pitch,
            boundary="WordBoundary",
        )
        chunks: list[bytes] = []
        duration_100ns = 0
        async for message in communicate.stream():
            if message["type"] == "audio":
                chunks.append(message["data"])
            elif message["type"] == "WordBoundary":
                duration_100ns = max(
                    duration_100ns,
                    int(message["offset"]) + int(message["duration"]),
                )
        if not chunks or duration_100ns <= 0:
            raise RuntimeError("Edge TTS returned no audio or timing metadata")
        return EdgeSynthesis(
            audio=b"".join(chunks),
            duration_ms=max(1, round(duration_100ns / 10_000)),
        )


@dataclass(frozen=True)
class AudioArtifacts:
    master_audio_path: Path
    manifest_path: Path
    cues_path: Path
    subtitle_path: Path
    timeline: Timeline


def _srt_time(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def _write_master(
    *, backend: SynthesisBackend, clips: list[Path], pauses_ms: list[int], output: Path
) -> None:
    if getattr(backend, "audio_format", None) != "mp3":
        output.write_bytes(b"".join(path.read_bytes() for path in clips))
        return
    ffmpeg = _ffmpeg_executable()
    with tempfile.TemporaryDirectory(prefix="book-video-audio-") as raw_tmp:
        tmp = Path(raw_tmp)
        parts: list[Path] = []
        for index, clip in enumerate(clips):
            parts.append(clip)
            pause = pauses_ms[index]
            if pause > 0:
                silence = tmp / f"silence-{index:04}.mp3"
                subprocess.run(
                    [
                        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                        "-t", f"{pause / 1000:.3f}", "-codec:a", "libmp3lame", str(silence),
                    ],
                    check=True,
                )
                parts.append(silence)
        concat_file = tmp / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{str(path.resolve()).replace(chr(39), chr(39) * 2)}'\n" for path in parts),
            encoding="utf-8",
        )
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-codec:a", "libmp3lame", str(output)],
            check=True,
        )


def _pause_gaps(timeline: Timeline) -> list[int]:
    """Return silence after every cue, including a fixed slot's final tail."""
    gaps: list[int] = []
    for index, cue in enumerate(timeline.cues):
        next_start = (
            timeline.cues[index + 1].start_ms
            if index + 1 < len(timeline.cues)
            else timeline.duration_ms
        )
        gaps.append(max(0, next_start - cue.end_ms))
    return gaps


def _mix_ambience(
    *,
    narration: Path,
    output: Path,
    project: ProjectSpec,
    timeline: Timeline,
    project_root: Path,
) -> None:
    ambient_scenes = [scene for scene in project.scenes if scene.ambience is not None]
    if not ambient_scenes:
        shutil.copyfile(narration, output)
        return

    command = [_ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(narration)]
    for scene in ambient_scenes:
        assert scene.ambience is not None
        ambience_path = (project_root / scene.ambience.file).resolve()
        if not ambience_path.is_relative_to(project_root.resolve()) or not ambience_path.is_file():
            raise ValueError(f"scene ambience is missing or unsafe: {scene.ambience.file}")
        command.extend(["-stream_loop", "-1", "-i", str(ambience_path)])

    filters: list[str] = []
    labels: list[str] = []
    start_ms = 0
    input_index = 1
    for scene in project.scenes:
        if scene.duration_ms is None:
            scene_cues = [cue for cue in timeline.cues if cue.scene_id == scene.id]
            scene_end = scene_cues[-1].end_ms + scene.lines[-1].pause_after_ms
            duration_ms = scene_end - scene_cues[0].start_ms
        else:
            duration_ms = scene.duration_ms
        if scene.ambience is not None:
            label = f"amb{input_index}"
            filters.append(
                f"[{input_index}:a]atrim=duration={duration_ms / 1000:.3f},"
                f"asetpts=PTS-STARTPTS,volume={scene.ambience.gain_db:g}dB,"
                f"adelay={start_ms}|{start_ms}[{label}]"
            )
            labels.append(f"[{label}]")
            input_index += 1
        start_ms += duration_ms
    filters.append(
        f"[0:a]{''.join(labels)}amix=inputs={1 + len(labels)}:"
        "duration=first:dropout_transition=0,alimiter=limit=0.95[out]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(output),
        ]
    )
    subprocess.run(command, check=True)


def _ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        executable = shutil.which("ffmpeg")
        if executable:
            return executable
    raise RuntimeError("ffmpeg is required to assemble and measure Edge TTS audio")


def _probe_mp3_ms(path: Path) -> int:
    ffmpeg = _ffmpeg_executable()
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", result.stderr)
    if not match:
        raise RuntimeError(f"could not measure audio duration: {path}")
    seconds = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
    return max(1, round(seconds * 1000))


class EdgeAudioRenderer:
    def __init__(self, *, backend: SynthesisBackend | None = None):
        self.backend = backend or EdgeTTSBackend()

    def render(
        self,
        *,
        project: ProjectSpec,
        output_dir: str | Path,
        project_root: str | Path | None = None,
    ) -> AudioArtifacts:
        validate_project(project)
        destination = Path(output_dir)
        clips_dir = destination / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        for stale_name in (
            "master.mp3",
            "narration.mp3",
            "manifest.json",
            "cues.json",
            "subtitles.srt",
        ):
            (destination / stale_name).unlink(missing_ok=True)

        durations: dict[str, int] = {}
        clip_entries: list[dict[str, Any]] = []
        clip_paths: list[Path] = []
        for scene in project.scenes:
            for line in scene.lines:
                speaker = project.speakers[line.speaker]
                result = self.backend.synthesize(
                    text=line.text,
                    voice=speaker.voice,
                    rate=speaker.rate,
                    volume=speaker.volume,
                    pitch=speaker.pitch,
                )
                if result.duration_ms <= 0 or not result.audio:
                    raise ValueError(f"invalid synthesis result for line {line.id}")
                clip_path = clips_dir / f"{line.id}.mp3"
                clip_path.write_bytes(result.audio)
                duration_ms = (
                    _probe_mp3_ms(clip_path)
                    if getattr(self.backend, "audio_format", None) == "mp3"
                    else int(result.duration_ms)
                )
                durations[line.id] = duration_ms
                clip_paths.append(clip_path)
                clip_entries.append(
                    {
                        "id": line.id,
                        "file": f"clips/{line.id}.mp3",
                        "duration_ms": duration_ms,
                        "sha256": hashlib.sha256(result.audio).hexdigest(),
                    }
                )

        timeline = build_timeline(project, line_durations_ms=durations)
        narration_master = destination / "narration.mp3"
        _write_master(
            backend=self.backend,
            clips=clip_paths,
            pauses_ms=_pause_gaps(timeline),
            output=narration_master,
        )
        master = destination / "master.mp3"
        has_ambience = any(scene.ambience is not None for scene in project.scenes)
        if has_ambience and project_root is None:
            raise ValueError("project_root is required when scene ambience is configured")
        _mix_ambience(
            narration=narration_master,
            output=master,
            project=project,
            timeline=timeline,
            project_root=Path(project_root or ".").resolve(),
        )
        cues = [
            {
                "id": cue.id,
                "kind": "line",
                "scene_id": cue.scene_id,
                "speaker": cue.speaker,
                "text": cue.text,
                "start": round(cue.start_ms / 1000, 3),
                "end": round(cue.end_ms / 1000, 3),
            }
            for cue in timeline.cues
        ]
        cues_path = destination / "cues.json"
        cues_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "duration_sec": round(timeline.duration_ms / 1000, 3),
                    "cues": cues,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest_path = destination / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": project.id,
                    "duration_ms": timeline.duration_ms,
                    "master_audio": "master.mp3",
                    "clips": clip_entries,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        subtitle_path = destination / "subtitles.srt"
        subtitle_path.write_text(
            "\n".join(
                f"{index}\n{_srt_time(cue.start_ms)} --> {_srt_time(cue.end_ms)}\n{cue.text}\n"
                for index, cue in enumerate(timeline.cues, start=1)
            ),
            encoding="utf-8",
        )
        return AudioArtifacts(
            master_audio_path=master,
            manifest_path=manifest_path,
            cues_path=cues_path,
            subtitle_path=subtitle_path,
            timeline=timeline,
        )
