from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy

import pytest
import yaml

from book_video.adaptation import (
    AdaptationValidationError,
    compile_adaptation,
    load_adaptation,
    write_adaptation_variants,
)


@pytest.fixture
def adaptation_data() -> dict:
    return {
        "version": 1,
        "adaptation": {
            "id": "loomings",
            "title": "Loomings",
            "language": "en-US",
            "source_file": "source.txt",
            "default_mode": "faithful",
            "target_duration_sec": 12,
        },
        "output": {"width": 1920, "height": 1080, "fps": 24},
        "narrator": {
            "id": "ishmael",
            "voice": "en-US-BrianMultilingualNeural",
        },
        "policy": {
            "narration_only": True,
            "forbid_future_knowledge": True,
        },
        "scenes": [
            {
                "id": "call_me_ishmael",
                "title": "Call Me Ishmael",
                "image": "assets/ishmael.png",
                "end_image": "assets/ishmael-at-harbor.png",
                "motion_prompt": "Ishmael watches the harbor, mouth closed, no visible speech.",
                "duration_ms": 12000,
                "source_refs": [
                    {"paragraph": "p001", "quote": "Call me Ishmael."}
                ],
                "interpretations": [
                    {
                        "kind": "production_choice",
                        "detail": "Ishmael wears a charcoal greatcoat.",
                    }
                ],
                "ambience": {
                    "description": "Distant harbor water and restrained wind.",
                    "file": "assets/ambience/harbor.mp3",
                    "gain_db": -24.0,
                },
                "narration": {
                    "faithful": "Call me Ishmael.",
                    "modern": "You can call me Ishmael.",
                    "pause_after_ms": 250,
                },
            }
        ],
    }


@pytest.fixture
def adaptation_file(tmp_path, adaptation_data):
    (tmp_path / "source.txt").write_text(
        "Call me Ishmael. Some years ago, I thought I would sail about a little.\n\n"
        "Look at the crowds of water-gazers there.\n",
        encoding="utf-8",
    )
    assets = tmp_path / "assets"
    (assets / "ambience").mkdir(parents=True)
    (assets / "ishmael.png").write_bytes(b"image")
    (assets / "ishmael-at-harbor.png").write_bytes(b"end-image")
    (assets / "ambience" / "harbor.mp3").write_bytes(b"audio")
    path = tmp_path / "adaptation.yaml"
    path.write_text(yaml.safe_dump(adaptation_data, sort_keys=False), encoding="utf-8")
    return path


def test_load_adaptation_validates_source_and_two_modes(adaptation_file):
    adaptation = load_adaptation(adaptation_file)

    assert adaptation.default_mode == "faithful"
    assert adaptation.target_duration_sec == 12
    assert adaptation.output.width == 1920
    assert adaptation.narrator.voice == "en-US-BrianMultilingualNeural"
    assert adaptation.scenes[0].narration.modern == "You can call me Ishmael."
    assert adaptation.scenes[0].source_refs[0].paragraph == "p001"


@pytest.mark.parametrize("mode", ["faithful", "modern"])
def test_compile_adaptation_keeps_one_shared_visual_plan(adaptation_file, mode):
    adaptation = load_adaptation(adaptation_file)

    project = compile_adaptation(adaptation, mode=mode)

    assert project.id == f"loomings_{mode}"
    assert project.output.width == 1920
    assert set(project.speakers) == {"ishmael"}
    assert project.scenes[0].image == "assets/ishmael.png"
    assert project.scenes[0].end_image == "assets/ishmael-at-harbor.png"
    assert project.scenes[0].motion_prompt == adaptation.scenes[0].motion_prompt
    assert project.scenes[0].duration_ms == 12000
    assert project.scenes[0].lines[0].text == getattr(
        adaptation.scenes[0].narration, mode
    )
    assert project.scenes[0].ambience.file == "assets/ambience/harbor.mp3"


def test_load_adaptation_rejects_faithful_words_not_present_in_source(
    adaptation_file, adaptation_data
):
    invalid = deepcopy(adaptation_data)
    invalid["scenes"][0]["narration"]["faithful"] = "A whale attacked Manhattan."
    adaptation_file.write_text(
        yaml.safe_dump(invalid, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(AdaptationValidationError, match="faithful.*source"):
        load_adaptation(adaptation_file)


def test_load_adaptation_rejects_unknown_or_mismatched_source_reference(
    adaptation_file, adaptation_data
):
    invalid = deepcopy(adaptation_data)
    invalid["scenes"][0]["source_refs"][0] = {
        "paragraph": "p999",
        "quote": "Call me Ishmael.",
    }
    adaptation_file.write_text(
        yaml.safe_dump(invalid, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(AdaptationValidationError, match="p999"):
        load_adaptation(adaptation_file)


def test_load_adaptation_rejects_future_knowledge_without_source_refs(
    adaptation_file, adaptation_data
):
    invalid = deepcopy(adaptation_data)
    invalid["scenes"][0]["source_refs"] = []
    adaptation_file.write_text(
        yaml.safe_dump(invalid, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(AdaptationValidationError, match="source_refs"):
        load_adaptation(adaptation_file)


def test_write_variants_emits_projects_provenance_and_ambience_plan(
    adaptation_file, tmp_path
):
    adaptation = load_adaptation(adaptation_file)
    output = tmp_path / "package"
    (output / "assets" / "ambience").mkdir(parents=True)
    (output / "assets" / "ishmael.png").write_bytes(b"image")
    (output / "assets" / "ishmael-at-harbor.png").write_bytes(b"end-image")
    (output / "assets" / "ambience" / "harbor.mp3").write_bytes(b"audio")

    artifacts = write_adaptation_variants(adaptation, output_dir=output)

    assert set(artifacts) == {"faithful", "modern"}
    faithful = yaml.safe_load((output / "project.faithful.yaml").read_text("utf-8"))
    modern = yaml.safe_load((output / "project.modern.yaml").read_text("utf-8"))
    assert faithful["scenes"][0]["image"] == modern["scenes"][0]["image"]
    assert faithful["scenes"][0]["lines"][0]["text"] == "Call me Ishmael."
    assert modern["scenes"][0]["lines"][0]["text"] == "You can call me Ishmael."
    provenance = json.loads((output / "provenance.json").read_text("utf-8"))
    ambience = json.loads((output / "ambience-plan.json").read_text("utf-8"))
    assert provenance["policy"]["forbid_future_knowledge"] is True
    assert provenance["scenes"][0]["source_refs"][0]["paragraph"] == "p001"
    assert ambience["scenes"][0]["gain_db"] == -24.0


def test_load_adaptation_rejects_unsupported_mode(adaptation_file, adaptation_data):
    invalid = deepcopy(adaptation_data)
    invalid["adaptation"]["default_mode"] = "mixed"
    adaptation_file.write_text(
        yaml.safe_dump(invalid, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(AdaptationValidationError, match="default_mode"):
        load_adaptation(adaptation_file)


def test_cli_adapt_builds_both_local_variants_without_colab(
    adaptation_file, tmp_path
):
    output = tmp_path / "handoff"
    env = {**os.environ, "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": ""}

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "book_video",
            "adapt",
            "--adaptation",
            str(adaptation_file),
            "--output-dir",
            str(output),
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
    assert payload["status"] == "adapted"
    assert payload["modes"] == ["faithful", "modern"]
    assert payload["target_duration_sec"] == 12
    assert (output / "project.faithful.yaml").is_file()
    assert (output / "project.modern.yaml").is_file()
    assert (output / "assets" / "ishmael.png").read_bytes() == b"image"
    assert not (output / "source.txt").exists()
