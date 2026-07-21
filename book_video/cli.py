from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

from .edge_audio import EdgeAudioRenderer
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
    audio = EdgeAudioRenderer().render(project=project, output_dir=args.output_dir / "audio")
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
        return _prepare(args) if args.command == "prepare" else _render(args)
    except (ProjectValidationError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
