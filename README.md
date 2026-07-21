# Book Video → Edge TTS → ComfyUI/LTX

Bu çalışma alanı, daha sonra vereceğiniz kitaptan hazırlanacak İngilizce kısa
film projesini iki parçaya ayırır:

1. `book_video`, çok konuşmacılı Edge TTS seslerini üretir; gerçek MP3
   sürelerinden `master.mp3`, upstream uyumlu `cues.json`, altyazı ve
   `spec.yaml` oluşturur.
2. Pinlenmiş `creative-skills/drama-video`, Colab içindeki özel ComfyUI
   sunucusunda sahne görsellerini LTX-2.3 ile canlandırıp `final.mp4` üretir.

Kitap geldiğinde Codex; uyarlama metnini, konuşmacıları, sahne bölünmesini,
promptları ve sahne görsellerini hazırlayacak. Bu repo üretim tesisidir; kitabın
kendisi veya telifli metin şimdiden repoya konmaz.

## Hazır Moby-Dick pilotu

Depo, 52.8 saniyelik dört sahneli ilk pilotu içerir. İngilizce Ishmael anlatımı,
altyazılar, cue zamanları ve dört sinematik başlangıç görseli önceden
hazırlanmıştır. Colab defteri `deliverables/moby_dick_pilot_colab.zip` paketini
otomatik açar; farklı bir proje seçilmedikçe `PROJECT_DIR` boş bırakılabilir.

## Yerel hazırlık

Python 3.11+ ve internet gerekir; paket kendi FFmpeg binary'sini getirir. Edge TTS konuşma metnini
Microsoft'un çevrimiçi TTS servisine gönderir.

```powershell
python -m pip install -e .
book-video prepare --project examples/minimal/project.yaml --output-dir build/minimal --dry-run --json
book-video prepare --project examples/minimal/project.yaml --output-dir build/minimal
```

İkinci komut şunları üretir:

```text
build/minimal/
  audio/clips/*.mp3
  audio/master.mp3
  audio/manifest.json
  audio/cues.json
  audio/subtitles.srt
  spec.yaml
```

Bir sahne 15 saniyeyi aşarsa derleme durur; LTX sınırına uygun yeni sahnelere
bölünmesi gerekir. Böylece replik ortasında kesme yapılmaz.

## Colab

[ComfyUI_Drama_Production.ipynb](notebooks/ComfyUI_Drama_Production.ipynb)
defterini Colab'a yükleyin. Repo URL'si hazır gelir; güvenli ve tekrarlanabilir
checkout için yayınlanan tam commit SHA'sını girin. Ayrıca Colab
Secrets içine `HF_TOKEN` ekleyin ve FLUX.2 Klein model koşullarını Hugging Face
üzerinde kabul edin.

Üretim manifesti [manifest.production.json](scripts/colab/manifest.production.json)
şunları sabitler:

- ComfyUI, creative-skills, KJNodes ve VideoHelperSuite commitleri
- Flux.2 Klein 9B FP8 ve LTX-2.3 22B model yolları
- gerekli ComfyUI node sınıfları
- en az 24 GB VRAM ve 120 GB boş disk preflight'ı

ComfyUI yalnızca `127.0.0.1:8188` üzerinde açılır. Cloudflare/ngrok benzeri
kimlik doğrulamasız public tünel kurulmaz.

## Render / devam etme

Hazırlanan proje klasörünü Colab/Drive'a koyduktan sonra defterde önce `plan`,
sonra tek bir `shot`, ardından `shots` ve `assemble` çalıştırın. Oturum koparsa
`status` mevcut dosyaları gösterir ve tamamlanan shot'lar upstream tarafından
atlanır.

Yerel CLI ile aynı backend çağrılabilir:

```powershell
book-video render --spec build/minimal/spec.yaml --stage plan
book-video render --spec build/minimal/spec.yaml --stage shot --shot-number 1
book-video render --spec build/minimal/spec.yaml --stage all --no-gate
```

## Doğrulama

```powershell
python -m pytest --cov=book_video
python scripts/colab/self_check.py
```

Canlı Edge TTS ve tam ComfyUI/LTX render testleri ağ, model lisans kabulü ve GPU
gerektirdiği için yerel mock testlerinden ayrıdır.
