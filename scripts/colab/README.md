# Colab runtime helpers

These files bootstrap a restartable, localhost-only ComfyUI runtime. The notebook is the user-facing entrypoint; `colab_runtime.py` keeps safety and idempotency rules testable outside Colab.

## Security and reproducibility contract

- Every Git repository is checked out at an exact 40-character commit SHA.
- Downloads use HTTPS, write through a `.part` file, and are skipped only when the existing file passes the supplied SHA-256/size check.
- Secrets are read from environment variables named by `token_env`; they never belong in the manifest or notebook.
- ComfyUI may bind only to loopback. There is no Cloudflare, localtunnel, ngrok, or other public tunnel support.
- Installation refuses a manifest with `manifest_complete: false`.
- Paths in the manifest must remain below the configured workspace.

## Manifest lifecycle

1. Copy `manifest.template.json` to `manifest.json`.
2. Set `COLAB_WORKSPACE`, `COMFYUI_COMMIT`, and `CREATIVE_SKILLS_COMMIT`.
3. Add reviewed `custom_nodes` and `assets`. Include SHA-256 whenever the publisher provides one.
4. List every model path and ComfyUI node class needed by the chosen production workflow.
5. Set `manifest_complete` to `true` only after review.
6. Run `python colab_runtime.py --manifest manifest.json validate` and then `host-preflight`.

The model/node manifest is intentionally separate from the notebook so changing a model never requires editing executable cells.

## Offline self-check

```bash
python scripts/colab/self_check.py
```

It checks pin enforcement, HTTPS enforcement, path traversal protection, checksum behavior, environment expansion, and the localhost bind guard without downloading anything.
