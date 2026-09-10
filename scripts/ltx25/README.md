# LTX-2.5 Pilot — Tek Sahne + Chatterbox Türkçe

Üretim hattının LTX-2.3 pinini bozmadan, yeni model ailesini tek sahne üzerinde
deneyen pilot paketi.

## Dosyalar

| Dosya | İş |
|---|---|
| `fetch_manifest.py` | Kapılı `Lightricks/LTX-2.5` deposundan HF_TOKEN ile SHA-256 çeker, pinli `manifest.ltx25.json` üretir |
| `pilot_workflow.py` | Resmî FLF2V şablonunu `/prompt` API graph'ına çevirir (`build_flf2v_graph`) |
| `pilot_run.py` | Uçtan uca koşum: preflight → install → ComfyUI → Chatterbox TR ses → render → mux → yükleme |

## Colab akışı

`notebooks/LTX25_Pilot.ipynb` üç hücre:

1. Repoyu pinli commit'ten çeker, `pip install -e .` + `chatterbox-tts` kurar
2. `HF_TOKEN` (Colab Secrets) ile manifest üretir
3. `pilot_run.py`'yi Sahne 1 kareleriyle çalıştırır

Ön koşullar: GPU runtime (L4/A100), HF_TOKEN secret'ı, LTX-2.5 lisans kabulü.

## Yerel test

```powershell
uv run pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-a tests/test_ltx25_pilot_workflow.py
uv run pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-b
```

## Tasarım kararları

- **Ses modelden gelmez:** LTX-2.5 senkron ses üretebilir ama pilot model sesini atar;
  Chatterbox'ın ürettiği mp3 `-c:v copy` ile mux'lanır (üretim hattındaki
  "orijinal WAV korunur" ilkesiyle aynı).
- **Manifest SHA'ları yerelde yazılamaz** (depo gated) — Colab'da HF'nin kendi
  tree API'sinden o an alınır, indirme sonrası `colab_runtime.download_asset`
  aynı SHA'ya karşı doğrular.
- **ComfyUI hâlâ yalnız `127.0.0.1:8188`.**
