from __future__ import annotations

import json
import os
import subprocess
import sys


def test_cli_dry_run_validates_and_prints_plan_without_network(project_file, tmp_path):
    env = {**os.environ, "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": ""}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "book_video",
            "prepare",
            "--project",
            str(project_file),
            "--output-dir",
            str(tmp_path / "result"),
            "--dry-run",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "status": "dry-run",
        "project_id": "clockwork_owl",
        "scene_count": 1,
        "line_count": 2,
        "estimated_duration_ms": None,
    }
    assert not (tmp_path / "result").exists()
