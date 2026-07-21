from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def valid_project_data() -> dict:
    """Small complete project used by contract tests."""
    return {
        "version": 1,
        "project": {
            "id": "clockwork_owl",
            "title": "The Clockwork Owl",
            "language": "en-US",
        },
        "output": {"width": 1280, "height": 720, "fps": 24},
        "speakers": {
            "narrator": {"voice": "en-US-GuyNeural"},
            "ada": {"voice": "en-US-JennyNeural"},
        },
        "scenes": [
            {
                "id": "workshop",
                "title": "The workshop",
                "image": "assets/workshop.png",
                "motion_prompt": "A slow push toward the workbench.",
                "lines": [
                    {
                        "id": "line_001",
                        "speaker": "narrator",
                        "text": "The workshop woke before dawn.",
                        "pause_after_ms": 200,
                    },
                    {
                        "id": "line_002",
                        "speaker": "ada",
                        "text": "Today, you will fly.",
                        "pause_after_ms": 0,
                    },
                ],
            }
        ],
    }


@pytest.fixture
def project_file(tmp_path: Path, valid_project_data: dict) -> Path:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "workshop.png").write_bytes(b"placeholder")
    path = tmp_path / "project.yaml"
    path.write_text(yaml.safe_dump(valid_project_data, sort_keys=False), encoding="utf-8")
    return path
