import json
from pathlib import Path


MANIFEST = Path("scripts/colab/manifest.production.json")
RUNTIME = Path("scripts/colab/colab_runtime.py")
NOTEBOOK = Path("notebooks/ComfyUI_Drama_Production.ipynb")
DRAMA_RENDERER = Path("vendor/creative-skills/drama-video/scripts/drama_video.py")
FLF_PATCH = Path("scripts/colab/patches/creative-skills-flf2v.patch")


def test_production_manifest_matches_verified_colab_limits_and_vae() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    vae = next(asset for asset in manifest["assets"] if asset["name"] == "Flux 2 VAE")

    assert manifest["preflight"]["minimum_free_disk_gb"] == 50
    assert vae["sha256"] == (
        "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3"
    )


def test_drive_runtime_avoids_shallow_git_fetch() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert 'run(["git", "fetch", "origin", commit], destination)' in source
    assert '"fetch", "--depth", "1"' not in source


def test_notebook_disables_optional_sageattention() -> None:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )

    assert 'os.environ["LTX_SAGE_ATTENTION"] = "off"' in code


def test_drama_renderer_routes_explicit_last_frame_to_audio_flf2v() -> None:
    source = FLF_PATCH.read_text(encoding="utf-8")

    assert 'shot.get("last_image")' in source
    assert '"flf2v"' in source
    assert '"--first", image_path' in source
    assert '"--last", last_image_path' in source
    assert '"--audio", str(slice_mp3)' in source


def test_production_manifest_applies_the_reviewed_flf2v_patch() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    creative = next(
        item for item in manifest["repositories"] if item["name"] == "creative-skills"
    )
    runtime = RUNTIME.read_text(encoding="utf-8")

    assert creative["patches"] == [
        "scripts/colab/patches/creative-skills-flf2v.patch"
    ]
    assert "apply_repository_patches(repository, path)" in runtime


def test_notebook_uses_five_minute_bundle_and_muxes_modern_variant() -> None:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )

    assert "deliverables/moby_dick_5m_colab.zip" in code
    assert 'spec_path = project_dir / "render_spec.yaml"' in code
    assert '"book_video", "mux"' in code
    assert 'modern_final = project_dir / "final-modern.mp4"' in code
