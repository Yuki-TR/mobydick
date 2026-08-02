#!/usr/bin/env python3
"""Safe, restartable Colab bootstrap helpers for ComfyUI drama rendering.

The manifest is deliberately data-driven: model URLs, checksums, node repositories,
and git commits are inputs rather than mutable values hidden in notebook cells.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Iterable


PIN_RE = re.compile(r"^[0-9a-fA-F]{40}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TOKEN_HOSTS = {"huggingface.co"}


class ConfigError(ValueError):
    """Raised when an unsafe or incomplete runtime configuration is detected."""


class TokenSafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward an authorization token away from its reviewed origin host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        if urlparse(req.full_url).hostname != urlparse(newurl).hostname:
            redirected.remove_header("Authorization")
        return redirected


def expand_env_value(value: Any) -> Any:
    if isinstance(value, str):
        expanded = os.path.expandvars(value)
        if re.search(r"\$\{[^}]+\}", expanded):
            raise ConfigError(f"Unresolved environment placeholder: {expanded}")
        return expanded
    if isinstance(value, list):
        return [expand_env_value(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_env_value(item) for key, item in value.items()}
    return value


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    manifest = expand_env_value(raw)
    validate_manifest(manifest)
    return manifest


def _require_https(url: str, label: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ConfigError(f"{label} must use HTTPS: {url!r}")
    if parsed.username or parsed.password:
        raise ConfigError(f"{label} must not contain URL credentials")


def _validate_repository(item: dict[str, Any], label: str) -> None:
    for key in ("name", "url", "commit", "destination"):
        if not item.get(key):
            raise ConfigError(f"{label}.{key} is required")
    _require_https(str(item["url"]), f"{label}.url")
    if not PIN_RE.fullmatch(str(item["commit"])):
        raise ConfigError(f"{label}.commit must be a 40-character git SHA")


def validate_manifest(manifest: dict[str, Any], require_complete: bool = False) -> None:
    if manifest.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")
    if not manifest.get("workspace"):
        raise ConfigError("workspace is required")
    if require_complete and not manifest.get("manifest_complete", False):
        raise ConfigError(
            "Manifest is marked incomplete. Add the reviewed official assets/nodes and set manifest_complete=true."
        )
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise ConfigError("repositories must contain at least ComfyUI and creative-skills")
    for index, item in enumerate(repositories):
        _validate_repository(item, f"repositories[{index}]")
    repository_names = {str(item["name"]).lower() for item in repositories}
    missing_repositories = {"comfyui", "creative-skills"} - repository_names
    if missing_repositories:
        raise ConfigError(
            "repositories is missing: " + ", ".join(sorted(missing_repositories))
        )
    for index, item in enumerate(manifest.get("custom_nodes", [])):
        _validate_repository(item, f"custom_nodes[{index}]")
    for index, item in enumerate(manifest.get("assets", [])):
        for key in ("name", "url", "destination"):
            if not item.get(key):
                raise ConfigError(f"assets[{index}].{key} is required")
        _require_https(str(item["url"]), f"assets[{index}].url")
        sha = item.get("sha256")
        if sha and not SHA256_RE.fullmatch(str(sha)):
            raise ConfigError(f"assets[{index}].sha256 must be 64 hexadecimal characters")
        if require_complete and not sha:
            raise ConfigError(f"assets[{index}].sha256 is required in a complete manifest")
        if item.get("token_env"):
            hostname = urlparse(str(item["url"])).hostname
            if hostname not in TOKEN_HOSTS:
                raise ConfigError(
                    f"assets[{index}].token_env may only be sent to {sorted(TOKEN_HOSTS)}"
                )
    for index, package in enumerate(manifest.get("python_packages", [])):
        if not isinstance(package, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+", package
        ):
            raise ConfigError(
                f"python_packages[{index}] must be an exact name==version pin"
            )
    if require_complete:
        preflight = manifest.get("preflight", {})
        if not manifest.get("assets"):
            raise ConfigError("A complete production manifest must list its model assets")
        if not preflight.get("required_model_paths"):
            raise ConfigError("A complete production manifest must list required_model_paths")
        if not preflight.get("required_node_classes"):
            raise ConfigError("A complete production manifest must list required_node_classes")


def workspace_root(manifest: dict[str, Any]) -> Path:
    return Path(str(manifest["workspace"])).expanduser().resolve()


def safe_destination(root: Path, relative: str) -> Path:
    value = Path(relative)
    if value.is_absolute():
        raise ConfigError(f"Destination must be relative to workspace: {relative}")
    destination = (root / value).resolve()
    try:
        destination.relative_to(root.resolve())
    except ValueError as exc:
        raise ConfigError(f"Destination escapes workspace: {relative}") from exc
    return destination


def run(command: list[str], cwd: Path | None = None) -> None:
    printable = " ".join(command)
    print(f"+ {printable}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def clone_pinned(item: dict[str, Any], root: Path) -> Path:
    destination = safe_destination(root, str(item["destination"]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    git_dir = destination / ".git"
    if not git_dir.exists():
        if destination.exists() and any(destination.iterdir()):
            raise ConfigError(f"Refusing to replace non-git directory: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        run(["git", "init"], destination)
        run(["git", "remote", "add", "origin", str(item["url"])], destination)
    else:
        current_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], cwd=destination, text=True
        ).strip()
        if current_url.rstrip("/") != str(item["url"]).rstrip("/"):
            raise ConfigError(
                f"Origin mismatch for {item['name']}: {current_url!r} != {item['url']!r}"
            )
    commit = str(item["commit"])
    # Google Drive's FUSE mount can change .git/shallow while a shallow fetch
    # reads it. A regular pinned fetch is larger but stable on persistent Drive.
    run(["git", "fetch", "origin", commit], destination)
    # A dirty persistent checkout is user state; fail instead of overwriting it.
    run(["git", "checkout", "--detach", "FETCH_HEAD"], destination)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=destination, text=True).strip()
    if actual.lower() != commit.lower():
        raise RuntimeError(f"Pinned checkout failed for {item['name']}: got {actual}")
    return destination


def install_requirements(repository: dict[str, Any], path: Path) -> None:
    for relative in repository.get("requirements", []):
        requirement_file = safe_destination(path, str(relative))
        if not requirement_file.is_file():
            if repository.get("required", True):
                raise ConfigError(f"Requirements file not found: {requirement_file}")
            print(f"WARN optional requirements file missing: {requirement_file}")
            continue
        run([sys.executable, "-m", "pip", "install", "-r", str(requirement_file)])
    if repository.get("pip_editable", False):
        run([sys.executable, "-m", "pip", "install", "-e", str(path)])


def apply_repository_patches(repository: dict[str, Any], path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    for relative in repository.get("patches", []):
        patch_path = safe_destination(project_root, str(relative))
        if not patch_path.is_file():
            raise ConfigError(f"Repository patch not found: {patch_path}")
        reverse_check = subprocess.run(
            ["git", "apply", "--reverse", "--check", str(patch_path)],
            cwd=path,
            check=False,
            capture_output=True,
            text=True,
        )
        if reverse_check.returncode == 0:
            print(f"SKIP already applied patch: {patch_path.name}")
            continue
        run(["git", "apply", "--check", str(patch_path)], path)
        run(["git", "apply", str(patch_path)], path)


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def asset_is_current(path: Path, sha256: str | None, minimum_bytes: int) -> bool:
    if not path.is_file() or path.stat().st_size < minimum_bytes:
        return False
    return not sha256 or sha256_file(path).lower() == sha256.lower()


def download_asset(item: dict[str, Any], root: Path) -> Path:
    destination = safe_destination(root, str(item["destination"]))
    sha256 = str(item["sha256"]) if item.get("sha256") else None
    minimum_bytes = int(item.get("minimum_bytes", 1))
    if asset_is_current(destination, sha256, minimum_bytes):
        print(f"SKIP verified asset: {item['name']} -> {destination}")
        return destination
    if destination.exists():
        print(f"REPLACE incomplete or unverifiable asset: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    if partial.exists():
        partial.unlink()
    headers = {"User-Agent": "comfy-drama-colab/1"}
    token_env = item.get("token_env")
    if token_env:
        token = os.environ.get(str(token_env))
        if not token:
            raise ConfigError(f"Required secret is absent from environment: {token_env}")
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(str(item["url"]), headers=headers)
    try:
        opener = urllib.request.build_opener(TokenSafeRedirectHandler())
        with opener.open(request, timeout=60) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output, length=8 * 1024 * 1024)
    except (OSError, urllib.error.URLError):
        partial.unlink(missing_ok=True)
        raise
    if not asset_is_current(partial, sha256, minimum_bytes):
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum/size validation failed for asset: {item['name']}")
    partial.replace(destination)
    print(f"OK asset: {item['name']} -> {destination}")
    return destination


def gpu_summary() -> str:
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ]
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("NVIDIA GPU is not available; select a GPU Colab runtime") from exc


def maximum_gpu_vram_gb(summary: str) -> float:
    memory_mib: list[float] = []
    for line in summary.splitlines():
        fields = [field.strip() for field in line.rsplit(",", 2)]
        if len(fields) != 3:
            raise RuntimeError(f"Could not parse nvidia-smi output: {line!r}")
        try:
            memory_mib.append(float(fields[1]))
        except ValueError as exc:
            raise RuntimeError(f"Could not parse GPU memory from: {line!r}") from exc
    if not memory_mib:
        raise RuntimeError("nvidia-smi reported no GPUs")
    return max(memory_mib) / 1024


def host_preflight(manifest: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    root = workspace_root(manifest)
    root.mkdir(parents=True, exist_ok=True)
    gpu = gpu_summary()
    print(f"GPU: {gpu}")
    available_vram = maximum_gpu_vram_gb(gpu)
    minimum_vram = float(manifest.get("preflight", {}).get("minimum_gpu_vram_gb", 0))
    print(f"Maximum GPU VRAM: {available_vram:.1f} GiB (required: {minimum_vram:.1f} GiB)")
    if available_vram < minimum_vram:
        raise RuntimeError(
            f"Insufficient GPU VRAM: {available_vram:.1f} GiB < {minimum_vram:.1f} GiB"
        )
    disk = shutil.disk_usage(root)
    free_gb = disk.free / (1024**3)
    minimum = float(manifest.get("preflight", {}).get("minimum_free_disk_gb", 25))
    print(f"Disk free: {free_gb:.1f} GiB (required: {minimum:.1f} GiB)")
    if free_gb < minimum:
        raise RuntimeError(f"Insufficient free disk: {free_gb:.1f} GiB < {minimum:.1f} GiB")
    for command in manifest.get("preflight", {}).get(
        "required_commands", ["git", "ffmpeg"]
    ):
        if shutil.which(command) is None:
            raise RuntimeError(f"Required command not found: {command}")
    if not manifest.get("manifest_complete", False):
        warnings.append("manifest_complete=false: install/render remain intentionally blocked")
    for item in manifest.get("assets", []):
        if not item.get("sha256"):
            warnings.append(f"asset has no checksum: {item['name']}")
    for warning in warnings:
        print(f"WARN {warning}")
    return warnings


def missing_node_classes(object_info: dict[str, Any], required: Iterable[str]) -> list[str]:
    return sorted(node for node in required if node not in object_info)


def installed_preflight(manifest: dict[str, Any]) -> None:
    root = workspace_root(manifest)
    failures: list[str] = []
    for repository in [*manifest.get("repositories", []), *manifest.get("custom_nodes", [])]:
        destination = safe_destination(root, str(repository["destination"]))
        if repository.get("required", True) and not (destination / ".git").is_dir():
            failures.append(f"repository missing: {repository['name']} ({destination})")
    for relative in manifest.get("preflight", {}).get("required_model_paths", []):
        path = safe_destination(root, str(relative))
        if not path.is_file():
            failures.append(f"model missing: {path}")
    if failures:
        raise RuntimeError("Installed preflight failed:\n- " + "\n- ".join(failures))
    print("Installed repository/model preflight passed")


def fetch_object_info(base_url: str) -> dict[str, Any]:
    assert_local_url(base_url)
    with urllib.request.urlopen(base_url.rstrip("/") + "/object_info", timeout=15) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected ComfyUI object_info response")
    return payload


def runtime_preflight(manifest: dict[str, Any], base_url: str) -> None:
    installed_preflight(manifest)
    required = manifest.get("preflight", {}).get("required_node_classes", [])
    missing = missing_node_classes(fetch_object_info(base_url), required)
    if missing:
        raise RuntimeError("Required ComfyUI node classes are missing:\n- " + "\n- ".join(missing))
    print(f"Runtime preflight passed ({len(required)} required node classes)")


def assert_local_bind(host: str) -> None:
    if host not in LOCAL_HOSTS:
        raise ConfigError(f"ComfyUI must remain localhost-only; refused bind host {host!r}")


def assert_local_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in LOCAL_HOSTS:
        raise ConfigError(f"Only localhost ComfyUI URLs are accepted: {url!r}")
    if parsed.username or parsed.password:
        raise ConfigError("Credentials are not allowed in the ComfyUI URL")


def launch_comfyui(manifest: dict[str, Any], host: str, port: int) -> None:
    assert_local_bind(host)
    root = workspace_root(manifest)
    comfy = next(
        (item for item in manifest["repositories"] if item["name"].lower() == "comfyui"), None
    )
    if comfy is None:
        raise ConfigError("A repository named ComfyUI is required")
    comfy_path = safe_destination(root, str(comfy["destination"]))
    main = comfy_path / "main.py"
    if not main.is_file():
        raise RuntimeError(f"ComfyUI entrypoint not found: {main}")
    state = root / ".colab_state"
    state.mkdir(parents=True, exist_ok=True)
    pid_path, log_path = state / "comfyui.pid", state / "comfyui.log"
    if pid_path.exists():
        try:
            existing = int(pid_path.read_text().strip())
            os.kill(existing, 0)
            print(f"ComfyUI already running as PID {existing}")
            return
        except (ValueError, OSError):
            pid_path.unlink(missing_ok=True)
    log = log_path.open("ab")
    process = subprocess.Popen(
        [sys.executable, str(main), "--listen", host, "--port", str(port)],
        cwd=comfy_path,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env={**os.environ, "COMFY_URL": f"http://{host}:{port}"},
    )
    log.close()
    pid_path.write_text(str(process.pid), encoding="utf-8")
    print(f"Started localhost-only ComfyUI PID {process.pid}; log: {log_path}")


def wait_server(url: str, timeout_seconds: int) -> None:
    assert_local_url(url)
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/system_stats", timeout=5) as response:
                if response.status == 200:
                    print(f"ComfyUI ready: {url}")
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"ComfyUI did not become ready within {timeout_seconds}s: {last_error}")


def install(manifest: dict[str, Any]) -> None:
    validate_manifest(manifest, require_complete=True)
    root = workspace_root(manifest)
    root.mkdir(parents=True, exist_ok=True)
    packages = list(manifest.get("python_packages", []))
    if packages:
        run([sys.executable, "-m", "pip", "install", *packages])
    for repository in manifest["repositories"]:
        path = clone_pinned(repository, root)
        apply_repository_patches(repository, path)
        install_requirements(repository, path)
    for node in manifest.get("custom_nodes", []):
        path = clone_pinned(node, root)
        install_requirements(node, path)
    for asset in manifest.get("assets", []):
        download_asset(asset, root)
    installed_preflight(manifest)


def render_status(manifest: dict[str, Any], project_dir: Path) -> None:
    root = workspace_root(manifest)
    project = project_dir.resolve()
    if not project.is_dir():
        raise ConfigError(f"Project directory not found: {project}")
    creative = next(
        (item for item in manifest["repositories"] if item["name"].lower() == "creative-skills"),
        None,
    )
    if creative is None:
        raise ConfigError("A repository named creative-skills is required")
    script = safe_destination(root, str(creative["destination"])) / "drama-video/scripts/drama_video.py"
    spec = project / "spec.yaml"
    run([sys.executable, str(script), "status", str(spec)], cwd=project)


def copy_outputs(source: Path, destination: Path) -> None:
    source, destination = source.resolve(), destination.resolve()
    if not source.is_dir():
        raise ConfigError(f"Output directory not found: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for pattern in ("*.mp4", "*.mp3", "*.wav", "*.srt", "*.json", "*.yaml"):
        for path in source.rglob(pattern):
            if path.is_symlink():
                raise ConfigError(f"Refusing to copy symlinked output: {path}")
            try:
                path.resolve().relative_to(source)
            except ValueError as exc:
                raise ConfigError(f"Output escapes source directory: {path}") from exc
            relative = path.relative_to(source)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
    print(f"Copied {copied} output artifact(s) to {destination}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--manifest", type=Path, required=True)
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    commands.add_parser("host-preflight")
    commands.add_parser("install")
    commands.add_parser("installed-preflight")
    launch = commands.add_parser("launch")
    launch.add_argument("--host", default="127.0.0.1")
    launch.add_argument("--port", type=int, default=8188)
    wait = commands.add_parser("wait")
    wait.add_argument("--url", default="http://127.0.0.1:8188")
    wait.add_argument("--timeout", type=int, default=300)
    runtime = commands.add_parser("runtime-preflight")
    runtime.add_argument("--url", default="http://127.0.0.1:8188")
    status = commands.add_parser("status")
    status.add_argument("--project-dir", type=Path, required=True)
    copy = commands.add_parser("copy-outputs")
    copy.add_argument("--source", type=Path, required=True)
    copy.add_argument("--destination", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "validate":
            print("Manifest structure valid")
        elif args.command == "host-preflight":
            host_preflight(manifest)
        elif args.command == "install":
            install(manifest)
        elif args.command == "installed-preflight":
            installed_preflight(manifest)
        elif args.command == "launch":
            launch_comfyui(manifest, args.host, args.port)
        elif args.command == "wait":
            wait_server(args.url, args.timeout)
        elif args.command == "runtime-preflight":
            runtime_preflight(manifest, args.url)
        elif args.command == "status":
            render_status(manifest, args.project_dir)
        elif args.command == "copy-outputs":
            copy_outputs(args.source, args.destination)
        return 0
    except (ConfigError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
