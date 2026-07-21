from __future__ import annotations

import json
from pathlib import Path

from book_video import cli


def test_main_dry_run_is_side_effect_free(project_file, tmp_path, capsys):
    output = tmp_path / "out"

    code = cli.main(
        [
            "prepare",
            "--project",
            str(project_file),
            "--output-dir",
            str(output),
            "--dry-run",
            "--json",
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry-run"
    assert not output.exists()


def test_main_reports_invalid_project(tmp_path, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text("version: 999\n", encoding="utf-8")

    code = cli.main(
        ["prepare", "--project", str(path), "--output-dir", str(tmp_path / "out")]
    )

    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_render_builds_safe_argument_list(monkeypatch, tmp_path):
    upstream = tmp_path / "upstream"
    script = upstream / "drama-video" / "scripts" / "drama_video.py"
    script.parent.mkdir(parents=True)
    script.write_text("# placeholder", encoding="utf-8")
    spec = tmp_path / "spec.yaml"
    spec.write_text("title: test", encoding="utf-8")
    recorded = {}

    class Result:
        returncode = 0

    def fake_run(command, *, check):
        recorded["command"] = command
        recorded["check"] = check
        return Result()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    code = cli.main(
        [
            "render",
            "--spec",
            str(spec),
            "--upstream",
            str(upstream),
            "--stage",
            "shot",
            "--shot-number",
            "2",
        ]
    )

    assert code == 0
    assert recorded["command"][1:] == [str(script), "shot", "2", str(spec)]
    assert recorded["check"] is False


def test_render_requires_shot_number(tmp_path, capsys):
    script = tmp_path / "upstream" / "drama-video" / "scripts" / "drama_video.py"
    script.parent.mkdir(parents=True)
    script.write_text("# placeholder", encoding="utf-8")

    code = cli.main(
        [
            "render",
            "--spec",
            str(tmp_path / "spec.yaml"),
            "--upstream",
            str(tmp_path / "upstream"),
            "--stage",
            "shot",
        ]
    )

    assert code == 2
    assert "shot-number" in capsys.readouterr().err


def test_prepare_contract_uses_spec_yaml(monkeypatch, project_file, tmp_path, capsys):
    project = cli.validate_project(cli.load_project(project_file))
    from book_video.edge_audio import AudioArtifacts
    from book_video.timeline import build_timeline

    timeline = build_timeline(
        project, line_durations_ms={"line_001": 1000, "line_002": 1000}
    )
    audio_dir = tmp_path / "out" / "audio"
    audio_dir.mkdir(parents=True)
    master = audio_dir / "master.mp3"
    cues = audio_dir / "cues.json"
    for path in (master, cues):
        path.write_bytes(b"x")

    class FakeRenderer:
        def render(self, **_kwargs):
            return AudioArtifacts(
                master_audio_path=master,
                manifest_path=audio_dir / "manifest.json",
                cues_path=cues,
                subtitle_path=audio_dir / "subtitles.srt",
                timeline=timeline,
            )

    monkeypatch.setattr(cli, "EdgeAudioRenderer", FakeRenderer)

    code = cli.main(
        [
            "prepare",
            "--project",
            str(project_file),
            "--output-dir",
            str(tmp_path / "out"),
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["spec"]).name == "spec.yaml"
    assert (tmp_path / "out" / "spec.yaml").is_file()
