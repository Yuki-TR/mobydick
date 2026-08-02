from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

from .adaptation import (
    AdaptationValidationError,
    load_adaptation,
    write_adaptation_variants,
)
from .edge_audio import EdgeAudioRenderer, _ffmpeg_executable
from .handoff import HandoffError, mux_variant, write_handoff_bundle
from .schema import (
    ProjectValidationError,
    load_project,
    validate_project,
    validate_project_assets,
)
from .upstream import build_drama_spec


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="book-video")
    commands = parser.add_subparsers(dest="command", required=True)
    adapt = commands.add_parser(
        "adapt", help="compile faithful and modern narration variants"
    )
    adapt.add_argument("--adaptation", type=Path, required=True)
    adapt.add_argument("--output-dir", type=Path, required=True)
    adapt.add_argument("--json", action="store_true", dest="as_json")

    bundle = commands.add_parser(
        "bundle", help="package one shared render plan and two prepared audio variants"
    )
    bundle.add_argument("--adaptation", type=Path, required=True)
    bundle.add_argument("--faithful-build", type=Path, required=True)
    bundle.add_argument("--modern-build", type=Path, required=True)
    bundle.add_argument("--output-dir", type=Path, required=True)
    bundle.add_argument("--archive", type=Path)
    bundle.add_argument("--json", action="store_true", dest="as_json")

    mux = commands.add_parser(
        "mux", help="reuse a rendered video with another narration and subtitles"
    )
    mux.add_argument("--video", type=Path, required=True)
    mux.add_argument("--audio", type=Path, required=True)
    mux.add_argument("--subtitles", type=Path)
    mux.add_argument("--output", type=Path, required=True)

    prepare = commands.add_parser("prepare", help="render Edge audio and compile drama YAML")
    prepare.add_argument("--project", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--dry-run", action="store_true")
    prepare.add_argument("--json", action="store_true", dest="as_json")

    render = commands.add_parser("render", help="run the pinned drama-video backend")
    render.add_argument("--spec", type=Path, required=True)
    render.add_argument("--upstream", type=Path, default=Path("vendor/creative-skills"))
    render.add_argument(
        "--stage",
        choices=("plan", "anchors", "shot", "shots", "assemble", "status", "all"),
        default="all",
    )
    render.add_argument("--shot-number", type=int)
    render.add_argument("--no-gate", action="store_true")
    return parser


def _prepare(args: argparse.Namespace) -> int:
    project = validate_project(load_project(args.project))
    if args.dry_run:
        result = {
            "status": "dry-run",
            "project_id": project.id,
            "scene_count": len(project.scenes),
            "line_count": sum(len(scene.lines) for scene in project.scenes),
            "estimated_duration_ms": None,
        }
        print(json.dumps(result) if args.as_json else yaml.safe_dump(result, sort_keys=False))
        return 0

    validate_project_assets(project, args.project.parent)
    audio = EdgeAudioRenderer().render(
        project=project,
        output_dir=args.output_dir / "audio",
        project_root=args.project.parent,
    )
    spec = build_drama_spec(
        project=project,
        timeline=audio.timeline,
        master_audio=audio.master_audio_path,
        cues_file=audio.cues_path,
        project_root=args.project.parent,
        spec_root=args.output_dir,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    spec_path = args.output_dir / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    result = {"status": "prepared", "spec": str(spec_path), "audio": str(audio.master_audio_path)}
    print(json.dumps(result) if args.as_json else yaml.safe_dump(result, sort_keys=False))
    return 0


def _adapt(args: argparse.Namespace) -> int:
    adaptation = load_adaptation(args.adaptation)
    artifacts = write_adaptation_variants(adaptation, output_dir=args.output_dir)
    result = {
        "status": "adapted",
        "adaptation_id": adaptation.id,
        "modes": list(artifacts),
        "target_duration_sec": adaptation.target_duration_sec,
        "projects": {mode: str(path) for mode, path in artifacts.items()},
    }
    print(json.dumps(result) if args.as_json else yaml.safe_dump(result, sort_keys=False))
    return 0


def _bundle(args: argparse.Namespace) -> int:
    adaptation = load_adaptation(args.adaptation)
    spec = write_handoff_bundle(
        adaptation,
        prepared_builds={
            "faithful": args.faithful_build,
            "modern": args.modern_build,
        },
        output_dir=args.output_dir,
        archive_path=args.archive,
    )
    result = {
        "status": "bundled",
        "render_spec": str(spec),
        "archive": str(args.archive) if args.archive else None,
    }
    print(json.dumps(result) if args.as_json else yaml.safe_dump(result, sort_keys=False))
    return 0


def _mux(args: argparse.Namespace) -> int:
    output = mux_variant(
        ffmpeg=_ffmpeg_executable(),
        video=args.video,
        audio=args.audio,
        subtitles=args.subtitles,
        output=args.output,
    )
    print(yaml.safe_dump({"status": "muxed", "output": str(output)}, sort_keys=False))
    return 0


def _render(args: argparse.Namespace) -> int:
    script = args.upstream / "drama-video" / "scripts" / "drama_video.py"
    if not script.is_file():
        raise FileNotFoundError(f"upstream drama renderer not found: {script}")
    command = [sys.executable, str(script), args.stage]
    if args.stage == "shot":
        if not args.shot_number or args.shot_number < 1:
            raise ValueError("--shot-number is required and must be >= 1 for stage=shot")
        command.append(str(args.shot_number))
    command.append(str(args.spec))
    if args.no_gate and args.stage == "all":
        command.append("--no-gate")
    return subprocess.run(command, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "adapt":
            return _adapt(args)
        if args.command == "bundle":
            return _bundle(args)
        if args.command == "mux":
            return _mux(args)
        return _prepare(args) if args.command == "prepare" else _render(args)
    except (
        AdaptationValidationError,
        HandoffError,
        ProjectValidationError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
