#!/usr/bin/env python3
"""Colab pilotu: LTX-2.5 distilled FLF2V ile tek sahneyi canlandır + Chatterbox Türkçe anlatımı mux'la.

Akış (repodaki üretim kalıplarıyla birebir):
  1. fetch_manifest.py ile üretilmiş pinli manifest'i yükle
  2. colab_runtime: host-preflight -> install (idempotent) -> launch -> wait
  3. Chatterbox Türkçe anlatım mp3'ü (SynthesisBackend protokolü, lazy model yükleme)
  4. build_flf2v_graph() ile /prompt API graph'ı gönder, /history ile bekle
  5. Model sesini at, orijinal anlatımı ffmpeg ile mux'la (handoff.build_mux_command)
  6. Çıktıyı uguu.se'ye yükleyip URL yazdır

Kullanım (Colab, repo kökünden):
  python scripts/ltx25/pilot_run.py --manifest manifest.ltx25.json \
      --first assets/keyframes/001_street.png --last assets/keyframes/002_coffin.png \
      --output-dir /content/pilot_out
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS = Path(__file__).resolve().parents[1]

DEFAULT_PROMPT = (
    "Use the provided start image as the first frame and the provided end image as the "
    "final frame anchor. Ishmael walks alone down a wet 1840s lower Manhattan street toward "
    "the harbor in fine November rain, his charcoal greatcoat moving naturally, a slow "
    "restrained dolly forward following him, distant carriage wheels and faint harbor wind, "
    "the street emptying toward the water, his figure steadying as rigging appears through "
    "the rain, photorealistic historical drama, stable face, mouth closed, no visible speech, "
    "no text."
)
DEFAULT_NARRATION_TR = (
    "Bana İsmail deyin. Denizde biraz dolaşmayı, dünyanın suyla dolu kısmını görmeyi düşündüm."
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


colab_runtime = _load_module("colab_runtime", SCRIPTS / "colab" / "colab_runtime.py")
from book_video import handoff  # noqa: E402 — paket importu, sys.path REPO_ROOT içeriyor


def _http_json(url: str, payload: dict | None = None, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def generate_narration(text: str, output: Path, *, language_id: str = "tr") -> dict:
    """Chatterbox Türkçe anlatım; SynthesisBackend protokolünü kullanır."""
    backend_mod = _load_module("chatterbox_backend", REPO_ROOT / "book_video" / "chatterbox_backend.py")
    backend = backend_mod.ChatterboxBackend()
    result = backend.synthesize(text=text, voice=language_id)
    output.write_bytes(result.audio)
    return {
        "file": str(output),
        "duration_ms": result.duration_ms,
        "language_id": result.language_id,
        "ignored_overrides": list(result.ignored_overrides),
    }


def render_video(
    *, base_url: str, graph_builder, graph_builder_module, comfy_input_dir: Path, first: Path, last: Path,
    prompt: str, duration_sec: int, width: int, height: int, fps: int, output_dir: Path,
    seed: int | None = None,
) -> Path:
    for image in (first, last):
        shutil.copy(image, comfy_input_dir / image.name)
    graph = graph_builder(
        prompt=prompt, first_image=first.name, last_image=last.name,
        width=width, height=height, fps=fps, duration_sec=duration_sec, seed=seed,
    )
    client_id = str(uuid.uuid4())
    payload = graph_builder_module.build_api_payload(graph, client_id=client_id)
    response = _http_json(base_url + "/prompt", payload)
    prompt_id = response["prompt_id"]
    print(f"prompt_id: {prompt_id} — render bekleniyor", flush=True)
    deadline = time.monotonic() + 60 * 60
    while time.monotonic() < deadline:
        history = _http_json(base_url + f"/history/{prompt_id}")
        if prompt_id in history:
            outputs = history[prompt_id].get("outputs", {})
            for node_output in outputs.values():
                for key in ("videos", "gifs", "images"):
                    for item in node_output.get(key, []):
                        name = item.get("filename")
                        if name:
                            source = comfy_input_dir.parent / "output" / name
                            if not source.is_file():
                                source = comfy_input_dir.parent / "output" / item.get("subfolder", "") / name
                            if source.is_file():
                                target = output_dir / "ltx25_render.mp4"
                                shutil.copy(source, target)
                                return target
            if history[prompt_id].get("status", {}).get("status_str") == "error":
                raise RuntimeError(f"render hata: {json.dumps(history[prompt_id].get('status'))[:500]}")
        time.sleep(10)
    raise RuntimeError("render 60 dk içinde bitmedi")


def mux_narration(video: Path, narration: Path, output: Path) -> Path:
    from book_video.edge_audio import _ffmpeg_executable  # noqa: PLC0415

    command = handoff.build_mux_command(
        ffmpeg=_ffmpeg_executable(), video=video, audio=narration, output=output
    )
    subprocess.run(command, check=True)
    return output


def upload_uguu(path: Path) -> str:
    boundary = "----bookvideopilot"
    data = path.read_bytes()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[]\"; "
        f"filename=\"{path.name}\"\r\nContent-Type: video/mp4\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        "https://uguu.se/upload", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.load(response)
    return payload["files"][0]["url"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--last", type=Path, required=True)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--narration-text", default=DEFAULT_NARRATION_TR)
    parser.add_argument("--narration-file", type=Path, default=None,
                        help="Hazır mp3 verilirse Chatterbox adımı atlanır")
    parser.add_argument("--duration", type=int, default=14)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--port", type=int, default=8188)
    parser.add_argument("--output-dir", type=Path, default=Path("pilot_out"))
    parser.add_argument("--skip-install", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = colab_runtime.load_manifest(args.manifest)
    base_url = f"http://127.0.0.1:{args.port}"

    colab_runtime.host_preflight(manifest)
    if not args.skip_install:
        colab_runtime.install(manifest)
    colab_runtime.launch_comfyui(manifest, "127.0.0.1", args.port)
    colab_runtime.wait_server(base_url, 600)

    narration_path = args.output_dir / "narration_tr.mp3"
    if args.narration_file is not None:
        shutil.copy(args.narration_file, narration_path)
        audio_info = {"file": str(narration_path), "source": "hazır dosya"}
    else:
        audio_info = generate_narration(args.narration_text, narration_path)
    print("anlatım:", json.dumps(audio_info), flush=True)

    workflow = _load_module("ltx25_api_graph", SCRIPTS / "ltx25" / "ltx25_api_graph.py")
    comfy_input_dir = colab_runtime.workspace_root(manifest) / "ComfyUI" / "input"
    video = render_video(
        base_url=base_url, graph_builder=workflow.build_flf2v_graph,
        graph_builder_module=workflow,
        comfy_input_dir=comfy_input_dir, first=args.first, last=args.last,
        prompt=args.prompt, duration_sec=args.duration, width=args.width,
        height=args.height, fps=args.fps, output_dir=args.output_dir, seed=args.seed,
    )
    print("video:", video, flush=True)

    final = mux_narration(video, narration_path, args.output_dir / "final_pilot_tr.mp4")
    print("final:", final, flush=True)
    try:
        print("indirme linki:", upload_uguu(final), flush=True)
    except Exception as exc:  # noqa: BLE001 — yükleme başarısız olsa da final yerelde durur
        print(f"yükleme başarısız ({exc}); dosya yerelde: {final}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
