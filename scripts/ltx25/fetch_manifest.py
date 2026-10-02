#!/usr/bin/env python3
"""manifest.ltx25.json üretici — kapılı Lightricks/LTX-2.5 deposu için.

SHA-256'lar yerelde bilinemez (depo gated); bu script Colab'da HF_TOKEN ile
Hugging Face tree API'sinden gerçek LFS oid'lerini çeker ve workspace'e
manifest yazar. İndirme doğrulaması (colab_runtime.download_asset) bu SHA
değerlerine karşı yapılır — yani kaynak HF'nin kendi API'si, doğrulama
kolaylaştırılmış değil, birebir pinli.

Kullanım (Colab):
    HF_TOKEN=... python scripts/ltx25/fetch_manifest.py --output /workspace/manifest.ltx25.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

REPO = "Lightricks/LTX-2.5"
# Resmî FLF2V workflow'unun kullandığı 4 dosya (docs.comfy.org LTX-2.5/FLF2V)
ASSETS = [
    {
        "name": "LTX 2.5 22B distilled transformer (comfy int8 convrot)",
        "path": "diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
        "destination": "ComfyUI/models/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
        "minimum_bytes": 20_000_000_000,
    },
    {
        "name": "Gemma 4 12B text encoder with projection (comfy int8 convrot)",
        "path": "text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
        "destination": "ComfyUI/models/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
        "minimum_bytes": 14_000_000_000,
    },
    {
        "name": "LTX 2.5 video VAE bf16",
        "path": "vae/ltx-2.5-video-vae-bf16.safetensors",
        "destination": "ComfyUI/models/vae/ltx-2.5-video-vae-bf16.safetensors",
        "minimum_bytes": 1_000_000_000,
    },
    {
        "name": "LTX 2.5 audio VAE bf16",
        "path": "vae/ltx-2.5-audio-vae-bf16.safetensors",
        "destination": "ComfyUI/models/vae/ltx-2.5-audio-vae-bf16.safetensors",
        "minimum_bytes": 300_000_000,
    },
]


def fetch_tree(token: str) -> dict[str, dict]:
    url = f"https://huggingface.co/api/models/{REPO}/tree/main?recursive=true"
    request = urllib.request.Request(url, headers={"User-Agent": "book-video-pilot/1", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return {entry["path"]: entry for entry in json.load(response)}


def build_manifest(token: str) -> dict:
    tree = fetch_tree(token)
    assets = []
    for spec in ASSETS:
        entry = tree.get(spec["path"])
        if entry is None:
            raise SystemExit(f"HATA: {spec['path']} depoda bulunamadı")
        lfs = entry.get("lfs") or {}
        sha = lfs.get("oid")
        # HF tree API her zaman oid_type dondurmez (null gelebilir); oid alanı
        # LFS icin sha256'dir. 64 hex karakterlik oid yeterli bir kanittir.
        oid_type = lfs.get("oid_type") or "sha256"
        if not sha or oid_type != "sha256" or len(sha) != 64:
            raise SystemExit(f"HATA: {spec['path']} icin sha256 oid alinamadi: {lfs}")
        assets.append(
            {
                "name": spec["name"],
                "url": f"https://huggingface.co/{REPO}/resolve/main/{spec['path']}",
                "destination": spec["destination"],
                "token_env": "HF_TOKEN",
                "sha256": sha,
                "minimum_bytes": spec["minimum_bytes"],
            }
        )
    return {
        "schema_version": 1,
        "manifest_complete": True,
        "workspace": "${COLAB_WORKSPACE}",
        "python_packages": ["PyYAML==6.0.3", "imageio-ffmpeg==0.6.0"],
        "repositories": [
            {
                "name": "ComfyUI",
                "url": "https://github.com/Comfy-Org/ComfyUI.git",
                "commit": "a7b1d39d342d102f305797fb5ba12dc304d9c1f5",
                "destination": "ComfyUI",
                "requirements": ["requirements.txt"],
                "required": True,
            },
            {
                "name": "creative-skills",
                "url": "https://github.com/venetanji/creative-skills.git",
                "commit": "741bab9bb1da495e96949286695fccfd3ec931ff",
                "destination": "creative-skills",
                "requirements": [],
                "patches": ["scripts/colab/patches/creative-skills-flf2v.patch"],
                "required": False,
            },
        ],
        "custom_nodes": [],
        "assets": assets,
        "preflight": {
            "minimum_free_disk_gb": 60,
            "minimum_gpu_vram_gb": 22,
            "required_model_paths": [a["destination"] for a in assets],
            "required_node_classes": [],
        },
        "notes": [
            "Pilot: LTX-2.5 distilled FLF2V, tek sahne. SHA'lar HF tree API'sinden o an alınır.",
            "Depo gated: HF hesabında LTX-2.5 lisansı kabul edilmiş olmalı.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--token-env", default="HF_TOKEN")
    args = parser.parse_args()
    token = os.environ.get(args.token_env, "")
    if not token:
        print(f"HATA: {args.token_env} ortam değişkeni yok", file=sys.stderr)
        return 2
    manifest = build_manifest(token)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"OK manifest yazıldı: {args.output} ({len(manifest['assets'])} varlık, SHA pinli)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
