from __future__ import annotations

import argparse
import math
import random
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

AMBIENCE_NAMES = (
    "rainy_city",
    "harbor",
    "stream",
    "ship_deck",
    "night_sea",
)


@dataclass(frozen=True)
class _SoundProfile:
    seed: int
    low_mix: float
    mid_mix: float
    high_mix: float
    lfo_hz: float
    lfo_depth: float
    rumble_hz: float


_PROFILES = {
    "rainy_city": _SoundProfile(1103, 0.12, 0.42, 0.22, 0.11, 0.18, 38.0),
    "harbor": _SoundProfile(2207, 0.38, 0.18, 0.04, 0.075, 0.55, 46.0),
    "stream": _SoundProfile(3301, 0.08, 0.42, 0.16, 0.37, 0.16, 72.0),
    "ship_deck": _SoundProfile(4409, 0.34, 0.20, 0.06, 0.095, 0.34, 55.0),
    "night_sea": _SoundProfile(5519, 0.50, 0.12, 0.02, 0.055, 0.65, 32.0),
}


def _clamp_sample(value: float) -> int:
    return max(-32767, min(32767, round(value * 32767)))


def _render_profile(
    profile: _SoundProfile, *, name: str, duration_sec: int, sample_rate: int
) -> array:
    rng = random.Random(profile.seed)
    frames = array("h")
    low = 0.0
    mid = 0.0
    side = 0.0
    total_frames = duration_sec * sample_rate
    for index in range(total_frames):
        time_sec = index / sample_rate
        noise = rng.uniform(-1.0, 1.0)
        side_noise = rng.uniform(-1.0, 1.0)
        low += 0.0018 * (noise - low)
        mid += 0.028 * (noise - mid)
        side += 0.016 * (side_noise - side)
        lfo = 1.0 - profile.lfo_depth + profile.lfo_depth * (
            0.5 + 0.5 * math.sin(2 * math.pi * profile.lfo_hz * time_sec)
        )
        rumble = math.sin(2 * math.pi * profile.rumble_hz * time_sec) * 0.035
        signal = (
            profile.low_mix * low
            + profile.mid_mix * mid
            + profile.high_mix * noise
            + rumble
        ) * lfo

        if name == "ship_deck":
            creak_phase = time_sec % 4.7
            if creak_phase < 0.8:
                envelope = math.sin(math.pi * creak_phase / 0.8) ** 2
                signal += 0.055 * envelope * math.sin(2 * math.pi * 118 * time_sec)
        elif name == "night_sea":
            breath_phase = time_sec % 9.5
            if 6.7 < breath_phase < 8.1:
                envelope = math.sin(math.pi * (breath_phase - 6.7) / 1.4) ** 2
                signal += envelope * mid * 0.18
        elif name == "stream":
            signal += 0.035 * math.sin(2 * math.pi * 3.1 * time_sec) * mid

        left = signal + side * 0.045
        right = signal - side * 0.045
        frames.append(_clamp_sample(left))
        frames.append(_clamp_sample(right))
    return frames


def generate_ambience_library(
    output_dir: str | Path, *, duration_sec: int = 12, sample_rate: int = 48_000
) -> dict[str, Path]:
    if isinstance(duration_sec, bool) or not isinstance(duration_sec, int) or duration_sec <= 0:
        raise ValueError("duration_sec must be a positive integer")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate < 8_000:
        raise ValueError("sample_rate must be an integer >= 8000")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, Path] = {}
    for name in AMBIENCE_NAMES:
        path = destination / f"{name}.wav"
        frames = _render_profile(
            _PROFILES[name], name=name, duration_sec=duration_sec, sample_rate=sample_rate
        )
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(2)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            audio.writeframes(frames.tobytes())
        artifacts[name] = path
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="book-video-ambience")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration-sec", type=int, default=12)
    args = parser.parse_args(argv)
    artifacts = generate_ambience_library(
        args.output_dir, duration_sec=args.duration_sec
    )
    for name, path in artifacts.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
