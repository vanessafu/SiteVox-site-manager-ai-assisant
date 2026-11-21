#!/usr/bin/env python3
"""Synthetische Baustellen-Audiodaten für ASR-Robustheitstests (und späteres Fine-Tuning).

Mischt saubere Sprachaufnahmen mit Baustellenlärm (Bagger, Rüttler, Wind, Regen) bei definierten SNRs.
Ohne Lärmdateien wird synthetischer Lärm erzeugt (Motorbrummen + Rauschen + Impulse).

  # Demo-Memos
  python scripts/data/audio/sythesize_noise_data.py --speech data/demo/BV-RIEM/inputs/2026-11-20 \
      --noise data/raw/noise --out data/asr_eval/noisy --snr 20 10 5 0
  # heruntergeladene Daten (scripts/data/audio/download_data.py → data/raw), z. B. nur Polnisch
  python scripts/data/audio/sythesize_noise_data.py --speech data/raw/speech/pl \
      --noise data/raw/noise --out data/asr_eval/noisy_pl

Sprach- und Lärmordner werden rekursiv durchsucht (.wav/.flac/.ogg/.mp3/.m4a; mp3/m4a benötigen librosa).
Referenztext: ASR-Fixture (Demo) oder transcripts.csv des Downloaders (wird automatisch gefunden).
Ausgabe: <out>/<stem>_snr<k>.wav + manifest.jsonl (Datei, SNR, Lärmquelle, Quelle, Referenztext).
Auswertung: WER je SNR mit der konfigurierten ASR (siehe sitevox.understand.asr).
SNR-Richtwerte: 20 dB Lärm hörbar · 10 dB laute Baustelle · 5 dB Maschine daneben · 0 dB so laut wie die Stimme.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Optional

import numpy as np

SR = 16000
AUDIO_EXT = {".wav", ".flac", ".ogg", ".mp3", ".m4a"}


def audio_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXT)


def load(path: Path) -> np.ndarray:
    import soundfile as sf

    if path.suffix.lower() in (".mp3", ".m4a"):  # libsndfile kann m4a nicht → librosa/ffmpeg
        import librosa

        x, _ = librosa.load(str(path), sr=SR, mono=True)
        return x.astype(np.float32)
    x, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != SR:
        n = int(len(x) * SR / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


def synthetic_noise(n: int, rng: np.random.Generator, kind: str) -> np.ndarray:
    t = np.arange(n) / SR
    if kind == "engine":  # Dieselmotor ~ 30–90 Hz + Harmonische
        f0 = rng.uniform(30, 90)
        x = sum(np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6.28)) / k for k in range(1, 8))
        x *= 1 + 0.3 * np.sin(2 * np.pi * rng.uniform(0.2, 1.0) * t)
    elif kind == "vibrator":  # Innenrüttler ~ 200 Hz
        x = np.sin(2 * np.pi * rng.uniform(180, 240) * t) + 0.3 * rng.standard_normal(n)
    elif kind == "impact":  # Hämmern
        x = 0.05 * rng.standard_normal(n)
        for pos in rng.integers(0, n, size=max(1, n // SR * 2)):
            L = min(800, n - pos)
            x[pos:pos + L] += np.exp(-np.arange(L) / 120) * rng.standard_normal(L)
    else:  # Wind/Regen: gefiltertes Rauschen
        w = rng.standard_normal(n)
        x = np.convolve(w, np.ones(32) / 32, mode="same") if kind == "wind" else w
    return (x / (np.max(np.abs(x)) + 1e-9)).astype(np.float32)


def mix(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    if len(noise) < len(speech):
        noise = np.tile(noise, int(np.ceil(len(speech) / len(noise))))
    start = random.randint(0, len(noise) - len(speech))
    noise = noise[start:start + len(speech)]
    ps, pn = np.mean(speech ** 2) + 1e-12, np.mean(noise ** 2) + 1e-12
    noise = noise * np.sqrt(ps / (pn * 10 ** (snr_db / 10)))
    y = speech + noise
    return (y / max(1.0, np.max(np.abs(y)) / 0.98)).astype(np.float32)


def find_transcripts(speech_dir: Path, explicit: Optional[str]) -> dict[str, str]:
    """Referenztexte aus transcripts.csv (Downloader); gesucht im Sprachordner und bis zu zwei Ebenen darüber."""
    cands = [Path(explicit)] if explicit else [d / "transcripts.csv" for d in [speech_dir, *speech_dir.parents[:2]]]
    for c in cands:
        if c.exists():
            with open(c, encoding="utf-8-sig", newline="") as f:
                return {Path(r["file"]).stem: r["text"] for r in csv.DictReader(f) if r.get("text")}
    return {}


def main() -> None:
    import soundfile as sf

    ap = argparse.ArgumentParser()
    ap.add_argument("--speech", required=True, help="Ordner mit sauberer Sprache (rekursiv)")
    ap.add_argument("--noise", default=None, help="Ordner mit Lärmaufnahmen, rekursiv (optional, sonst synthetisch)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--snr", nargs="+", type=float, default=[20, 10, 5, 0])
    ap.add_argument("--fixtures", default="data/demo/BV-RIEM/fixtures/asr", help="Referenztexte (ASR-Fixtures)")
    ap.add_argument("--transcripts", default=None, help="transcripts.csv (Standard: automatisch suchen)")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    random.seed(a.seed)
    rng = np.random.default_rng(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    noises = [(p.stem, load(p)) for p in audio_files(Path(a.noise))] if a.noise else []
    speech_files = audio_files(Path(a.speech))
    refs = find_transcripts(Path(a.speech).resolve(), a.transcripts)
    print(f"{len(speech_files)} Sprachdateien, {len(noises) or 'synthetischer'} Lärm, {len(refs)} Referenztexte")
    with open(out / "manifest.jsonl", "w", encoding="utf-8") as man:
        for sp in speech_files:
            s = load(sp)
            if np.max(np.abs(s)) < 1e-4:
                print(f"überspringe {sp.name} (Stille – mit make_demo_data.py --tts echte Sprache erzeugen)")
                continue
            ref = refs.get(sp.stem)
            fx = Path(a.fixtures) / f"{sp.stem}.json"
            if ref is None and fx.exists():
                ref = " ".join(seg["text"] for seg in json.loads(fx.read_text(encoding="utf-8"))["segments"])
            for snr in a.snr:
                if noises:
                    name, nz = random.choice(noises)
                else:
                    name = random.choice(["engine", "vibrator", "impact", "wind", "rain"])
                    nz = synthetic_noise(len(s), rng, name)
                y = mix(s, nz, snr)
                dst = out / f"{sp.stem}_snr{int(snr)}.wav"
                sf.write(str(dst), y, SR)
                man.write(json.dumps({"file": str(dst), "snr_db": snr, "noise": name, "source": str(sp),
                                      "text": ref}, ensure_ascii=False) + "\n")
                print(f"{dst.name}  SNR {snr:>4} dB  Lärm {name}")


if __name__ == "__main__":
    main()
