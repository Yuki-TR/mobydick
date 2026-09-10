"""Unit tests for the Chatterbox backend — no GPU, no chatterbox install.

``import chatterbox`` is never executed: the model loader is monkeypatched in
every test that reaches ``synthesize``. Waveform fakes mimic the real API
contract: ``generate`` returns a ``(1, N)`` float tensor (anything with
``.detach().cpu().reshape(-1).tolist()``) at 24 kHz.
"""

from __future__ import annotations

import inspect
import io
import json
import types
import wave

import pytest

import book_video.chatterbox_backend as cb
from book_video.chatterbox_backend import (
    CHATTERBOX_SAMPLE_RATE,
    SUPPORTED_LANGUAGES,
    ChatterboxBackend,
    ChatterboxSynthesis,
    _load_model,
    _tensor_to_wav_bytes,
    _volume_gain,
    _wav_duration_ms,
    _wav_to_mp3,
    supported_languages,
)

pytest.importorskip("imageio_ffmpeg")  # real MP3 encode/probe paths below


class FakeWav:
    """Mimics the ``(1, N)`` torch tensor returned by ``generate``."""

    def __init__(self, samples):
        self.samples = tuple(samples)

    def detach(self):
        return self

    def cpu(self):
        return self

    def reshape(self, shape=-1):
        assert shape == -1
        return self

    def tolist(self):
        return list(self.samples)


class FakeModel:
    """Records generate() kwargs; emits a deterministic 24 kHz waveform."""

    def __init__(self, samples=(0.0, 0.5, -0.5, 0.25, 0.0)):
        self.samples = tuple(samples)
        self.calls: list[dict] = []

    def generate(self, text, language_id, **kwargs):
        self.calls.append({"text": text, "language_id": language_id, **kwargs})
        return FakeWav(self.samples)


def install_fake_model(monkeypatch, **fake_kwargs) -> FakeModel:
    fake = FakeModel(**fake_kwargs)
    monkeypatch.setattr(cb, "_load_model", lambda *, device=None: fake)
    return fake


@pytest.fixture
def fresh_language_table():
    """Snapshot SUPPORTED_LANGUAGES; restore after tests that mutate it."""
    original = dict(SUPPORTED_LANGUAGES)
    yield SUPPORTED_LANGUAGES
    SUPPORTED_LANGUAGES.clear()
    SUPPORTED_LANGUAGES.update(original)


# ---------------------------------------------------------------- languages


def test_language_table_has_23_languages_including_turkish():
    assert len(SUPPORTED_LANGUAGES) == 23
    assert SUPPORTED_LANGUAGES["tr"] == "Turkish"
    expected = {
        "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it",
        "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh",
    }
    assert set(SUPPORTED_LANGUAGES) == expected


def test_supported_languages_helpers_return_copies():
    module_copy = supported_languages()
    static_copy = ChatterboxBackend.supported_languages()
    module_copy["zz"] = "Zzz"
    static_copy["zz"] = "Zzz"
    assert "zz" not in SUPPORTED_LANGUAGES


# ------------------------------------------------------- protocol conformance


def test_backend_matches_synthesis_backend_protocol_signature():
    """Structural check: SynthesisBackend is not runtime_checkable."""
    from book_video.edge_audio import SynthesisBackend

    def params(func) -> dict[str, inspect.Parameter]:
        return {
            name: parameter
            for name, parameter in inspect.signature(func).parameters.items()
            if name != "self"
        }

    protocol = params(SynthesisBackend.synthesize)
    implementation = params(ChatterboxBackend.synthesize)
    assert list(implementation) == list(protocol) == [
        "text", "voice", "rate", "volume", "pitch",
    ]
    for name, parameter in protocol.items():
        assert implementation[name].kind is parameter.kind
        if parameter.default is not inspect.Parameter.empty:
            assert implementation[name].default == parameter.default


def test_synthesis_result_satisfies_synthesis_result_protocol():
    from book_video.edge_audio import SynthesisResult

    result = ChatterboxSynthesis(audio=b"x", duration_ms=10)
    for attribute in inspect.get_annotations(SynthesisResult):
        assert hasattr(result, attribute)
    assert result.audio == b"x" and result.duration_ms == 10


def test_backend_uses_mp3_master_pipeline():
    assert ChatterboxBackend.audio_format == "mp3"


# ------------------------------------------------------------------- voice


def test_voice_language_code_is_resolved_case_insensitively(monkeypatch):
    fake = install_fake_model(monkeypatch)
    backend = ChatterboxBackend()

    backend.synthesize(text="Merhaba dünya.", voice="TR")

    assert fake.calls[0]["language_id"] == "tr"


def test_voice_rejects_unknown_language(monkeypatch):
    install_fake_model(monkeypatch)
    backend = ChatterboxBackend()

    with pytest.raises(ValueError, match="unsupported Chatterbox language 'zz'"):
        backend.synthesize(text="Hi.", voice="zz")


def test_voice_empty_is_rejected(monkeypatch):
    install_fake_model(monkeypatch)
    backend = ChatterboxBackend()

    with pytest.raises(ValueError, match="voice"):
        backend.synthesize(text="Hi.", voice="  ")


def test_voice_reference_wav_forwards_audio_prompt_path(tmp_path, monkeypatch):
    fake = install_fake_model(monkeypatch)
    reference = tmp_path / "speaker.wav"
    reference.write_bytes(b"fake wav")
    backend = ChatterboxBackend()

    backend.synthesize(text="Klonlanmış ses.", voice=str(reference))

    call = fake.calls[0]
    assert call["audio_prompt_path"] == str(reference)
    assert call["language_id"] == ""


def test_voice_reference_wav_must_exist(tmp_path, monkeypatch):
    install_fake_model(monkeypatch)
    backend = ChatterboxBackend()

    with pytest.raises(FileNotFoundError, match="missing.wav"):
        backend.synthesize(text="Hi.", voice=str(tmp_path / "missing.wav"))


# ---------------------------------------------------------------- generate


def test_synthesize_passes_generation_parameters(monkeypatch):
    fake = install_fake_model(monkeypatch)
    backend = ChatterboxBackend(exaggeration=0.7, cfg_weight=0.3, temperature=0.9)

    backend.synthesize(text="Nedelcem bu?", voice="tr")

    call = fake.calls[0]
    assert call["text"] == "Nedelcem bu?"
    assert call["exaggeration"] == 0.7
    assert call["cfg_weight"] == 0.3
    assert call["temperature"] == 0.9


def test_synthesize_empty_text_is_rejected(monkeypatch):
    install_fake_model(monkeypatch)
    backend = ChatterboxBackend()

    with pytest.raises(ValueError, match="empty text"):
        backend.synthesize(text="   ", voice="tr")


def test_synthesize_returns_mp3_with_waveform_duration(tmp_path, monkeypatch):
    install_fake_model(
        monkeypatch,
        samples=tuple(
            0.3 * ((index % 8) - 4) / 4 for index in range(CHATTERBOX_SAMPLE_RATE // 2)
        ),  # 0.5 s at 24 kHz
    )
    backend = ChatterboxBackend()

    result = backend.synthesize(text="Merhaba dünya.", voice="tr")

    assert isinstance(result, ChatterboxSynthesis)
    assert result.duration_ms == 500
    assert result.language_id == "tr"
    assert result.ignored_overrides == ()
    header = result.audio[:3]
    assert header == b"ID3" or (result.audio[0] == 0xFF and (result.audio[1] & 0xE0) == 0xE0)
    from book_video.edge_audio import _probe_mp3_ms

    clip = tmp_path / "clip.mp3"
    clip.write_bytes(result.audio)
    assert _probe_mp3_ms(clip) == pytest.approx(500, abs=120)


def test_synthesize_records_ignored_rate_and_pitch(monkeypatch):
    install_fake_model(monkeypatch)
    backend = ChatterboxBackend()

    result = backend.synthesize(
        text="Hızlı.", voice="tr", rate="+10%", volume="+20%", pitch="-5Hz"
    )

    assert result.ignored_overrides == ("rate", "pitch")
    assert _volume_gain("+20%") == pytest.approx(1.2)


def test_synthesize_neutral_overrides_are_not_reported(monkeypatch):
    install_fake_model(monkeypatch)

    result = ChatterboxBackend().synthesize(text="Normal.", voice="tr")

    assert result.ignored_overrides == ()


# ------------------------------------------------- model loading & caching


def test_load_model_requires_chatterbox_package(monkeypatch):
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "chatterbox" or name.startswith("chatterbox."):
            raise ImportError("No module named 'chatterbox'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    monkeypatch.setattr(cb, "_MODEL_CACHE", {})

    with pytest.raises(RuntimeError, match="chatterbox is not installed"):
        _load_model()


def test_load_model_uses_installed_language_table_and_caches(
    monkeypatch, fresh_language_table
):
    fake_mtl = types.ModuleType("chatterbox.mtl_tts")

    class FakeMultilingualTTS:
        @classmethod
        def from_pretrained(cls, *, device):
            return ("fake-model", device)

    fake_mtl.ChatterboxMultilingualTTS = FakeMultilingualTTS
    fake_chatterbox = types.ModuleType("chatterbox")
    fake_chatterbox.SUPPORTED_LANGUAGES = {"xx": "Fake"}
    fake_chatterbox.mtl_tts = fake_mtl
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "chatterbox":
            return fake_chatterbox
        if name == "chatterbox.mtl_tts":
            return fake_mtl
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    monkeypatch.setattr(cb, "_MODEL_CACHE", {})

    model = _load_model(device="cpu")

    assert model == ("fake-model", "cpu")
    assert fresh_language_table == {"xx": "Fake"}
    assert cb._MODEL_CACHE["cpu"] == model
    assert _load_model(device="cpu") is model  # served from cache


# ------------------------------------------------------------- wav helpers


def test_volume_gain_translates_edge_percentages():
    assert _volume_gain(None) == 1.0
    assert _volume_gain("") == 1.0
    assert _volume_gain("garbage") == 1.0
    assert _volume_gain("+0%") == 1.0
    assert _volume_gain("+50%") == pytest.approx(1.5)
    assert _volume_gain("-50%") == pytest.approx(0.5)
    assert _volume_gain("-150%") == 0.0  # never negative


def test_tensor_to_wav_bytes_writes_16bit_mono_pcm():
    payload = _tensor_to_wav_bytes(
        FakeWav([0.0, 0.5, -0.5, 1.0, -1.0, 2.0]), CHATTERBOX_SAMPLE_RATE
    )

    with wave.open(io.BytesIO(payload)) as reader:
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == 2
        assert reader.getframerate() == CHATTERBOX_SAMPLE_RATE
        raw = reader.readframes(reader.getnframes())
    assert len(raw) == 6 * 2
    assert _wav_duration_ms(payload) == 1  # 6 samples @ 24 kHz -> 1 ms floor


def test_tensor_to_wav_bytes_applies_gain_and_clamps():
    import array as array_module

    def pcm_values(payload):
        with wave.open(io.BytesIO(payload)) as reader:
            raw = reader.readframes(reader.getnframes())
        values = array_module.array("h")
        values.frombytes(raw)
        return [abs(value) for value in values]

    loud = _tensor_to_wav_bytes(FakeWav([0.5]), CHATTERBOX_SAMPLE_RATE, gain=1.5)
    quiet = _tensor_to_wav_bytes(FakeWav([0.5]), CHATTERBOX_SAMPLE_RATE, gain=0.5)
    clipped = _tensor_to_wav_bytes(FakeWav([4.0]), CHATTERBOX_SAMPLE_RATE)

    assert pcm_values(loud) == [24575]  # 0.75 * 32767
    assert pcm_values(quiet) == [8192]  # 0.25 * 32767
    assert pcm_values(clipped) == [32112]  # 4.0 normalized to 0.98 full scale


def test_tensor_to_wav_bytes_rejects_empty_waveform():
    with pytest.raises(ValueError, match="no audio samples"):
        _tensor_to_wav_bytes(FakeWav([]), CHATTERBOX_SAMPLE_RATE)


def test_wav_duration_ms_rounds_and_floors_at_one():
    one_second = _tensor_to_wav_bytes(
        FakeWav([0.0] * CHATTERBOX_SAMPLE_RATE), CHATTERBOX_SAMPLE_RATE
    )
    tiny = _tensor_to_wav_bytes(FakeWav([0.0] * 12), CHATTERBOX_SAMPLE_RATE)

    assert _wav_duration_ms(one_second) == 1000
    assert _wav_duration_ms(tiny) == 1


def test_wav_to_mp3_transcodes_with_ffmpeg():
    tone = _tensor_to_wav_bytes(
        FakeWav([0.25 * ((index % 16) - 8) / 8 for index in range(CHATTERBOX_SAMPLE_RATE)]),
        CHATTERBOX_SAMPLE_RATE,
    )

    mp3 = _wav_to_mp3(tone)

    assert mp3[:3] == b"ID3" or (mp3[0] == 0xFF and (mp3[1] & 0xE0) == 0xE0)


def test_wav_to_mp3_surfaces_ffmpeg_failures(monkeypatch):
    class FakeCompleted:
        returncode = 1
        stdout = b""
        stderr = b"boom"

    monkeypatch.setattr(cb.subprocess, "run", lambda *a, **k: FakeCompleted())

    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        _wav_to_mp3(b"not really a wav")


# ------------------------------------------------- EdgeAudioRenderer e2e


def test_renderer_end_to_end_with_chatterbox_backend(
    tmp_path, valid_project_data, monkeypatch
):
    """Full render path: real MP3 encode + ffmpeg probe, fake model only."""
    import yaml

    from book_video.edge_audio import EdgeAudioRenderer
    from book_video.schema import load_project

    valid_project_data["speakers"] = {
        "narrator": {"voice": "en"},
        "ada": {"voice": "tr"},
    }
    project_path = tmp_path / "project.yaml"
    project_path.write_text(
        yaml.safe_dump(valid_project_data, sort_keys=False), encoding="utf-8"
    )

    half_second = [
        0.3 * ((index % 8) - 4) / 4 for index in range(CHATTERBOX_SAMPLE_RATE // 2)
    ]

    class ModelPair:
        def __init__(self):
            self.calls: list[dict] = []

        def generate(self, text, language_id, **kwargs):
            self.calls.append({"text": text, "language_id": language_id, **kwargs})
            return FakeWav(half_second)

    fake = ModelPair()
    monkeypatch.setattr(cb, "_load_model", lambda *, device=None: fake)

    artifacts = EdgeAudioRenderer(backend=ChatterboxBackend()).render(
        project=load_project(project_path),
        output_dir=tmp_path / "audio",
    )

    assert [call["language_id"] for call in fake.calls] == ["en", "tr"]
    manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    # MP3 pipeline active: durations probed via ffmpeg, not the header value.
    assert all(400 <= clip["duration_ms"] <= 700 for clip in manifest["clips"])
    assert artifacts.master_audio_path.stat().st_size > 0
    assert artifacts.master_audio_path.name == "master.mp3"
