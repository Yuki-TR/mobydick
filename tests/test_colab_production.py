import json
from pathlib import Path


MANIFEST = Path("scripts/colab/manifest.production.json")
RUNTIME = Path("scripts/colab/colab_runtime.py")
NOTEBOOK = Path("notebooks/ComfyUI_Drama_Production.ipynb")


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
