from __future__ import annotations

import hashlib
import wave

from book_video.ambience import AMBIENCE_NAMES, generate_ambience_library


def test_generate_ambience_library_writes_deterministic_stereo_wav_files(tmp_path):
    first = generate_ambience_library(
        tmp_path / "first", duration_sec=1, sample_rate=8000
    )
    second = generate_ambience_library(
        tmp_path / "second", duration_sec=1, sample_rate=8000
    )

    assert set(first) == set(AMBIENCE_NAMES)
    for name in AMBIENCE_NAMES:
        with wave.open(str(first[name]), "rb") as audio:
            assert audio.getnchannels() == 2
            assert audio.getsampwidth() == 2
            assert audio.getframerate() == 8000
            assert audio.getnframes() == 8000
        assert hashlib.sha256(first[name].read_bytes()).digest() == hashlib.sha256(
            second[name].read_bytes()
        ).digest()


def test_generate_ambience_library_rejects_unsafe_or_invalid_settings(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="duration"):
        generate_ambience_library(tmp_path / "bad", duration_sec=0)
    with pytest.raises(ValueError, match="sample_rate"):
        generate_ambience_library(tmp_path / "bad", sample_rate=100)
