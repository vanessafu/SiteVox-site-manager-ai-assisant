"""Mix clean voice recordings with construction-site noise at fixed SNR levels.

Usage:
    pip install numpy soundfile librosa
    python mix_noise.py <voice_dir> <noise_dir> <out_dir> [snr_db ...]

Example:
    python mix_noise.py data/voice/clean data/noise data/voice/noisy 15 10 5 0

For each voice file and each SNR it writes  <voice>__<noise>__snr<X>dB.wav  (16 kHz mono, the
format Whisper expects) and a mix_log.csv listing what was mixed with what.
SNR guide: 15 dB = noise clearly audible, 10 dB = loud site, 5 dB = machine next to you,
0 dB = noise as loud as the speaker.
"""
import csv
import random
import sys
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

SR = 16000
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}


def load(path):
    y, _ = librosa.load(path, sr=SR, mono=True)
    return y.astype(np.float32)


def rms(x):
    return float(np.sqrt(np.mean(x ** 2) + 1e-12))


def fit_noise(noise, n, rng):
    """Cut (or loop) the noise to exactly n samples, starting at a random offset."""
    if len(noise) < n:
        noise = np.tile(noise, int(np.ceil(n / len(noise))) + 1)
    start = rng.randint(0, len(noise) - n)
    return noise[start:start + n]


def mix(voice, noise, snr_db):
    gain = rms(voice) / (rms(noise) * 10 ** (snr_db / 20))
    out = voice + gain * noise
    peak = np.max(np.abs(out))
    return out / peak * 0.95 if peak > 0.99 else out  # avoid clipping


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    voice_dir, noise_dir, out_dir = map(Path, sys.argv[1:4])
    snrs = [float(s) for s in sys.argv[4:]] or [15, 10, 5, 0]
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)

    voices = sorted(p for p in voice_dir.iterdir() if p.suffix.lower() in AUDIO_EXT)
    noises = sorted(p for p in noise_dir.iterdir() if p.suffix.lower() in AUDIO_EXT)
    if not voices or not noises:
        sys.exit(f"Found {len(voices)} voice and {len(noises)} noise files - need at least one of each.")
    noise_audio = {p: load(p) for p in noises}

    with open(out_dir / "mix_log.csv", "w", newline="", encoding="utf-8") as f:
        log = csv.writer(f)
        log.writerow(["output", "voice", "noise", "snr_db"])
        for v in voices:
            voice = load(v)
            for snr in snrs:
                n_path = rng.choice(noises)
                noisy = mix(voice, fit_noise(noise_audio[n_path], len(voice), rng), snr)
                name = f"{v.stem}__{n_path.stem}__snr{snr:g}dB.wav"
                sf.write(out_dir / name, noisy, SR)
                log.writerow([name, v.name, n_path.name, snr])
                print("wrote", name)


if __name__ == "__main__":
    main()
