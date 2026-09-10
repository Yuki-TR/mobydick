"""Local Chatterbox Multilingual TTS backend for the book_video pipeline.

Drop-in replacement for :class:`book_video.edge_audio.EdgeTTSBackend` that runs
resemble-ai/chatterbox's ``ChatterboxMultilingualTTS`` locally (23 languages,
including ``tr``). The heavy ``chatterbox``/``torch`` imports happen lazily
inside :func:`_load_model`, so importing this module never requires the
package, a GPU, or a model download.

The renderer pipeline (``EdgeAudioRenderer``) is MP3-based end to end: clip
durations are probed with ffmpeg (``_probe_mp3_ms``) and the narration master
is assembled with the MP3 concat demuxer plus libmp3lame silence at 24 kHz
mono. Chatterbox emits 24 kHz mono float audio, so this backend transcodes
each clip to 24 kHz mono MP3 and advertises ``audio_format = "mp3"`` — no
renderer changes are needed to swap backends.
"""

from __future__ import annotations

import array
import io
import re
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .edge_audio import _ffmpeg_executable

CHATTERBOX_SAMPLE_RATE = 24_000  # S3GEN_SR: Chatterbox's synthesis sample rate
_MP3_BITRATE = "64k"  # transparent for 24 kHz mono speech

# Mirrors chatterbox.mtl_tts.SUPPORTED_LANGUAGES (resemble-ai/chatterbox
# master). Refreshed from the installed package at model load time so language
# validation works before and after ``import chatterbox``.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "ar": "Arabic",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "ms": "Malay",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "sv": "Swedish",
    "sw": "Swahili",
    "tr": "Turkish",
    "zh": "Chinese",
}

# Loaded ChatterboxMultilingualTTS instances keyed by torch device string.
_MODEL_CACHE: dict[str, Any] = {}


def supported_languages() -> dict[str, str]:
    """Return the supported Chatterbox language codes and display names."""
    return dict(SUPPORTED_LANGUAGES)


def _select_device() -> str:
    """Pick the best available torch device (imported lazily by callers)."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    backends = getattr(torch, "backends", None)
    mps = getattr(backends, "mps", None) if backends is not None else None
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def _load_model(*, device: str | None = None) -> Any:
    """Import chatterbox lazily and return a cached ChatterboxMultilingualTTS."""
    try:
        import chatterbox  # noqa: F401  (presence guard; heavy deps load here)
    except ImportError as exc:
        raise RuntimeError(
            "chatterbox is not installed; install the chatterbox-tts package "
            "(GPU/CUDA or CPU torch) to use ChatterboxBackend"
        ) from exc

    device = device or _select_device()
    model = _MODEL_CACHE.get(device)
    if model is None:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        installed_languages = getattr(chatterbox, "SUPPORTED_LANGUAGES", None)
        if isinstance(installed_languages, dict) and installed_languages:
            SUPPORTED_LANGUAGES.clear()
            SUPPORTED_LANGUAGES.update(installed_languages)
        model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        _MODEL_CACHE[device] = model
    return model


def _volume_gain(volume: str | None) -> float:
    """Translate an Edge SSML ``volume`` percentage into a linear gain.

    Unparsable values are treated as neutral so malformed speaker config can
    never crash synthesis.
    """
    match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*%\s*", volume or "")
    if not match:
        return 1.0
    return max(0.0, 1.0 + float(match.group(1)) / 100.0)


def _tensor_to_wav_bytes(wav: Any, sample_rate: int, *, gain: float = 1.0) -> bytes:
    """Convert a ``(1, N)`` float waveform tensor to 16-bit mono WAV bytes.

    Uses only ``tensor.tolist()`` plus the stdlib ``array``/``wave`` modules,
    so no numpy or soundfile dependency is required. ``gain`` is applied as a
    linear multiplier and the waveform is clamped/normalized to full scale.
    """
    samples = wav.detach().cpu().reshape(-1).tolist()
    if not samples:
        raise ValueError("Chatterbox returned no audio samples")
    if gain != 1.0:
        samples = [value * gain for value in samples]
    peak = max(abs(value) for value in samples)
    if peak > 1.0:
        scale = 0.98 / peak
        samples = [value * scale for value in samples]
    frames = array.array(
        "h", (round(max(-1.0, min(1.0, value)) * 32767) for value in samples)
    )
    if sys.byteorder == "big":  # wave expects little-endian PCM
        frames.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(frames.tobytes())
    return buffer.getvalue()


def _wav_duration_ms(wav_bytes: bytes) -> int:
    """Measure WAV length from its RIFF header (stdlib only)."""
    try:
        with wave.open(io.BytesIO(wav_bytes)) as reader:
            sample_rate = reader.getframerate() or CHATTERBOX_SAMPLE_RATE
            frames = reader.getnframes()
    except wave.Error as exc:
        raise ValueError("could not measure Chatterbox wav duration") from exc
    return max(1, round(frames * 1000 / sample_rate))


def _wav_to_mp3(wav_bytes: bytes) -> bytes:
    """Transcode WAV bytes to 24 kHz mono MP3 via ffmpeg stdin/stdout pipes."""
    ffmpeg = _ffmpeg_executable()
    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", "pipe:0",
            "-codec:a", "libmp3lame", "-b:a", _MP3_BITRATE,
            "-ar", str(CHATTERBOX_SAMPLE_RATE), "-ac", "1",
            "-f", "mp3", "pipe:1",
        ],
        input=wav_bytes,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(
            f"ffmpeg failed to encode Chatterbox audio to mp3: {stderr[:400]}"
        )
    return result.stdout


@dataclass(frozen=True)
class ChatterboxSynthesis:
    """SynthesisResult with Chatterbox provenance metadata.

    ``duration_ms`` is measured from the generated waveform header before MP3
    transcoding; the renderer re-probes the MP3 clip because
    ``audio_format == "mp3"``.
    """

    audio: bytes
    duration_ms: int
    language_id: str | None = None
    ignored_overrides: tuple[str, ...] = ()


class ChatterboxBackend:
    """Local Chatterbox Multilingual TTS backend satisfying SynthesisBackend.

    ``voice`` is either a Chatterbox language code (``"tr"``, ``"en"``, ...
    case-insensitive) or a path to a reference WAV for voice cloning, which is
    forwarded as ``audio_prompt_path``.

    Edge SSML ``rate``/``pitch`` overrides have no Chatterbox equivalent and
    are recorded in ``ignored_overrides``; ``volume`` is applied as linear
    gain.
    """

    audio_format = "mp3"

    def __init__(
        self,
        *,
        device: str | None = None,
        exaggeration: float = 0.5,
        cfg_weight: float = 0.5,
        temperature: float = 0.8,
    ):
        self.device = device
        self.exaggeration = exaggeration
        self.cfg_weight = cfg_weight
        self.temperature = temperature

    @staticmethod
    def supported_languages() -> dict[str, str]:
        return dict(SUPPORTED_LANGUAGES)

    @staticmethod
    def _resolve_voice(voice: str) -> tuple[str, Path | None]:
        candidate = (voice or "").strip()
        if not candidate:
            raise ValueError(
                "speaker voice must be a Chatterbox language code or a reference wav path"
            )
        if "/" in candidate or "\\" in candidate or candidate.lower().endswith(".wav"):
            reference = Path(candidate)
            if not reference.is_file():
                raise FileNotFoundError(f"voice reference wav not found: {candidate}")
            return "", reference
        language_id = candidate.lower()
        if language_id not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"unsupported Chatterbox language '{candidate}'; supported languages: "
                f"{', '.join(sorted(SUPPORTED_LANGUAGES))}"
            )
        return language_id, None

    def synthesize(
        self,
        *,
        text: str,
        voice: str,
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ) -> ChatterboxSynthesis:
        if not text.strip():
            raise ValueError("cannot synthesize empty text")
        language_id, audio_prompt_path = self._resolve_voice(voice)
        model = _load_model(device=self.device)
        wav = model.generate(
            text,
            language_id,
            audio_prompt_path=(
                str(audio_prompt_path) if audio_prompt_path is not None else None
            ),
            exaggeration=self.exaggeration,
            cfg_weight=self.cfg_weight,
            temperature=self.temperature,
        )
        wav_bytes = _tensor_to_wav_bytes(
            wav, CHATTERBOX_SAMPLE_RATE, gain=_volume_gain(volume)
        )
        duration_ms = _wav_duration_ms(wav_bytes)
        ignored = tuple(
            name
            for name, value, neutral in (
                ("rate", rate, "+0%"),
                ("pitch", pitch, "+0Hz"),
            )
            if value not in (None, "", neutral)
        )
        return ChatterboxSynthesis(
            audio=_wav_to_mp3(wav_bytes),
            duration_ms=duration_ms,
            language_id=language_id or None,
            ignored_overrides=ignored,
        )
