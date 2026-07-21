#!/usr/bin/env python3
"""Offline structural checks for the Colab runtime helpers."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import colab_runtime as runtime


PIN = "a" * 40


def valid_manifest(root: Path) -> dict:
    return {
        "schema_version": 1,
        "workspace": str(root),
        "repositories": [
            {
                "name": "ComfyUI",
                "url": "https://github.com/comfyanonymous/ComfyUI.git",
                "commit": PIN,
                "destination": "ComfyUI",
                "required": True,
            },
            {
                "name": "creative-skills",
                "url": "https://github.com/venetanji/creative-skills.git",
                "commit": PIN,
                "destination": "creative-skills",
                "required": True,
            },
        ],
        "assets": [],
        "custom_nodes": [],
        "preflight": {
            "minimum_free_disk_gb": 1,
            "required_model_paths": [],
            "required_node_classes": [],
        },
    }


class ManifestChecks(unittest.TestCase):
    def test_accepts_minimal_pinned_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime.validate_manifest(valid_manifest(Path(temp)))

    def test_rejects_unpinned_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manifest = valid_manifest(Path(temp))
            manifest["repositories"][0]["commit"] = "main"
            with self.assertRaisesRegex(runtime.ConfigError, "40-character"):
                runtime.validate_manifest(manifest)

    def test_complete_validation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manifest = valid_manifest(Path(temp))
            with self.assertRaisesRegex(runtime.ConfigError, "marked incomplete"):
                runtime.validate_manifest(manifest, require_complete=True)

    def test_rejects_insecure_download_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manifest = valid_manifest(Path(temp))
            manifest["assets"] = [
                {"name": "model", "url": "http://example.test/model", "destination": "ComfyUI/models/x.bin"}
            ]
            with self.assertRaisesRegex(runtime.ConfigError, "HTTPS"):
                runtime.validate_manifest(manifest)

    def test_rejects_token_exfiltration_host(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manifest = valid_manifest(Path(temp))
            manifest["assets"] = [
                {
                    "name": "model",
                    "url": "https://evil.example/model",
                    "destination": "ComfyUI/models/x.bin",
                    "token_env": "HF_TOKEN",
                    "sha256": "0" * 64,
                }
            ]
            with self.assertRaisesRegex(runtime.ConfigError, "only be sent"):
                runtime.validate_manifest(manifest)

    def test_complete_manifest_requires_asset_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manifest = valid_manifest(Path(temp))
            manifest["manifest_complete"] = True
            manifest["assets"] = [
                {
                    "name": "model",
                    "url": "https://huggingface.co/org/model/resolve/main/model.bin",
                    "destination": "ComfyUI/models/x.bin",
                }
            ]
            with self.assertRaisesRegex(runtime.ConfigError, "sha256"):
                runtime.validate_manifest(manifest, require_complete=True)

    def test_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(runtime.ConfigError):
                runtime.safe_destination(root, "../outside")

    def test_expands_environment_placeholders(self) -> None:
        with mock.patch.dict("os.environ", {"MODEL_URL": "https://example.test/model"}):
            self.assertEqual(
                runtime.expand_env_value("${MODEL_URL}"),
                "https://example.test/model",
            )


class DownloadChecks(unittest.TestCase):
    def test_checksum_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "asset.bin"
            path.write_bytes(b"asset")
            expected = hashlib.sha256(b"asset").hexdigest()
            self.assertTrue(runtime.asset_is_current(path, expected, 1))

    def test_checksum_mismatch_is_not_current(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "asset.bin"
            path.write_bytes(b"asset")
            self.assertFalse(runtime.asset_is_current(path, "0" * 64, 1))


class RuntimeChecks(unittest.TestCase):
    def test_gpu_vram_parser_uses_largest_device(self) -> None:
        summary = "NVIDIA T4, 15360, 550.1\nNVIDIA A100, 40960, 550.1"
        self.assertEqual(runtime.maximum_gpu_vram_gb(summary), 40.0)

    def test_localhost_guard_rejects_public_bind(self) -> None:
        with self.assertRaisesRegex(runtime.ConfigError, "localhost-only"):
            runtime.assert_local_bind("0.0.0.0")

    def test_localhost_url_guard_rejects_remote_server(self) -> None:
        with self.assertRaisesRegex(runtime.ConfigError, "localhost"):
            runtime.assert_local_url("https://example.test:8188")

    def test_localhost_url_guard_rejects_prefix_trick(self) -> None:
        with self.assertRaisesRegex(runtime.ConfigError, "localhost"):
            runtime.assert_local_url("http://localhost.example.test:8188")

    def test_parse_object_info_reports_missing_classes(self) -> None:
        missing = runtime.missing_node_classes(
            {"LoadImage": {}}, ["LoadImage", "LTXVConditioning"]
        )
        self.assertEqual(missing, ["LTXVConditioning"])

    def test_load_manifest_expands_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = valid_manifest(root)
            manifest["workspace"] = "${COLAB_WORKSPACE}"
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with mock.patch.dict("os.environ", {"COLAB_WORKSPACE": str(root)}):
                loaded = runtime.load_manifest(path)
            self.assertEqual(loaded["workspace"], str(root))


if __name__ == "__main__":
    unittest.main(verbosity=2)
