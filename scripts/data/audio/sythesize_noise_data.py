#!/usr/bin/env python3
"""Synthetische Baustellen-Audiodaten für ASR-Robustheitstests (und späteres Fine-Tuning).

Mischt saubere Sprachaufnahmen mit Baustellenlärm bei definierten SNRs und erzeugt zusätzlich reine Lärm-/Stille-
Clips (text "") zur Messung von Halluzinationen. Echter Lärm (download_data.py → data/raw/noise) wird bevorzugt;
synthetischer Lärm (Motorbrummen, Rüttler, Hämmern, Wind, Regen) nur, wenn kein Lärmordner vorhanden ist.

  # Manifest-Eingabe (z. B. aus tts_synthesize.py) – alle Felder werden übernommen, id bekommt _snr{k}
  python scripts/data/audio/sythesize_noise_data.py --manifest data/asr_eval/clean/manifest.jsonl \
      --out data/asr_eval/noisy
  # Ordner-Eingabe (Demo-Memos / heruntergeladene Sprache), Referenz aus transcripts.csv oder ASR-Fixtures
  python scripts/data/audio/sythesize_noise_data.py --speech data/raw/speech/de_cv --out data/asr_eval/noisy_cv

Ausgabe: <out>/<id>_snr<k>.wav, <out>/noise_only/*.wav und <out>/manifest.jsonl im Format von evaluation/eval_asr.py:
  {"id", "file", "text", "snr_db", "noise", "noise_file", "clean_file", ...alle Felder der Eingabe...}
Mit --clean (Standard) steht zusätzlich je Eingabe eine Zeile snr_db="clean" (Originaldatei) im Manifest.
Pegelmodell (--level):
  phone (Standard)  Handy direkt vor dem Mund: Stimme fest auf --speech-dbfs (−18 dBFS aktive Sprache), Lärm wird
                    ABSOLUT lauter; Übersteuerung → weicher Limiter (Lärmspitzen sättigen, Stimme bleibt laut).
                    SNR 15 10 5 0 −5 dB. Optional --codec opus (wie MediaRecorder im Browser).
  relative          altes Verhalten: Lärm relativ skaliert, danach Peak-Normalisierung → Stimme wird bei 0 dB leiser.
SNR (bezogen auf aktive Sprache): 15 dB ruhige Baustelle · 5 dB Bagger in 10 m · 0 dB Rüttler/Säge daneben ·
−5 dB Presslufthammer direkt daneben (Handy am Mund hält meist noch ≥ −5 dB).
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Optional

import numpy as np

SR = 16000
AUDIO_EXT = {".wav", ".flac", ".ogg", ".mp3", ".m4a"}
SYNTH_KINDS = ["engine", "vibrator", "impact", "wind", "rain"]
DEFAULT_NOISE = Path(__file__).resolve().parents[3] / "data" / "raw" / "noise"


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
    elif kind == "wind":  # tieffrequent gefiltertes Rauschen mit Böen
        x = np.convolve(rng.standard_normal(n), np.ones(32) / 32, mode="same")
        x *= 1 + 0.6 * np.sin(2 * np.pi * rng.uniform(0.1, 0.4) * t)
    else:  # Regen: Rauschen + viele kurze Tropfen-Impulse
        x = 0.3 * rng.standard_normal(n)
        for pos in rng.integers(0, n, size=max(1, n // SR * 60)):
            L = min(60, n - pos)
            x[pos:pos + L] += rng.uniform(0.5, 1.5) * np.exp(-np.arange(L) / 10) * rng.standard_normal(L)
    return (x / (np.max(np.abs(x)) + 1e-9)).astype(np.float32)


class NoiseBank:
    """Echte Lärmaufnahmen, gruppiert nach Klasse (= Unterordner, z. B. urbansound8k_jackhammer)."""

    def __init__(self, folder: Optional[Path], rng: np.random.Generator):
        self.rng = rng
        self.classes: dict[str, list[tuple[str, np.ndarray]]] = {}
        if folder and folder.exists():
            for p in audio_files(folder):
                x = load(p)
                if np.max(np.abs(x)) > 1e-4:
                    cls = p.parent.name if p.parent != folder else p.stem
                    self.classes.setdefault(cls, []).append((p.stem, x))
        self.synthetic = not self.classes

    def names(self) -> list[str]:
        return SYNTH_KINDS if self.synthetic else sorted(self.classes)

    def sample(self, n: int, cls: Optional[str] = None) -> tuple[str, str, np.ndarray]:
        """→ (Klasse, Datei, Lärm der Länge n). Klassen werden gleichverteilt gezogen, nicht nach Dateizahl."""
        cls = cls or self.names()[self.rng.integers(len(self.names()))]
        if self.synthetic:
            return cls, "synthetic", synthetic_noise(n, self.rng, cls)
        stem, x = self.classes[cls][self.rng.integers(len(self.classes[cls]))]
        if len(x) < n:
            x = np.tile(x, int(np.ceil(n / len(x))))
        s = int(self.rng.integers(0, len(x) - n + 1))
        return cls, stem, x[s:s + n]


def mix(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    """level=relative (alt): Lärm relativ zur Sprache skaliert, danach Peak-Normalisierung des Mixes – bei niedrigem
    SNR wird damit auch die STIMME leiser (unrealistisch für ein Handy direkt vor dem Mund)."""
    ps, pn = np.mean(speech ** 2) + 1e-12, np.mean(noise ** 2) + 1e-12
    y = speech + noise * np.sqrt(ps / (pn * 10 ** (snr_db / 10)))
    return (y / max(1.0, np.max(np.abs(y)) / 0.98)).astype(np.float32)


def dbfs(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12))


def active_rms(x: np.ndarray, frame: int = 400) -> float:
    """RMS nur über Sprach-Frames (Energie > Median−… ), damit Pausen den Pegel nicht verdünnen."""
    n = len(x) // frame
    if n < 3:
        return float(np.sqrt(np.mean(x ** 2)) + 1e-12)
    e = np.sqrt(np.mean(x[: n * frame].reshape(n, frame) ** 2, axis=1))
    thr = max(np.percentile(e, 30), 0.1 * e.max())
    return float(np.sqrt(np.mean(e[e >= thr] ** 2)) + 1e-12)


def soft_limit(y: np.ndarray, knee: float = 0.7) -> tuple[np.ndarray, float]:
    """Weicher Limiter wie im Handy-Aufnahmepfad: unter knee linear, darüber tanh-Sättigung bis 1.0.
    → Lärmspitzen werden verzerrt/abgeflacht, die Stimme bleibt laut. Rückgabe: Signal, Anteil gesättigter Samples."""
    a = np.abs(y)
    over = a > knee
    out = y.copy()
    out[over] = np.sign(y[over]) * (knee + (1 - knee) * np.tanh((a[over] - knee) / (1 - knee)))
    return (out * 0.99).astype(np.float32), float(over.mean())


def mix_phone(speech: np.ndarray, noise: np.ndarray, snr_db: float, speech_dbfs: float) -> tuple[np.ndarray, dict]:
    """level=phone: Handy-Nahbesprechung. Die Stimme wird auf einen festen, lauten Pegel gebracht (Mund ~5 cm vom
    Mikrofon) und bleibt dort; der Lärm wird ABSOLUT lauter gemacht (SNR bezogen auf die aktive Sprache). Übersteuerung
    fängt ein weicher Limiter ab (statt den ganzen Mix leiser zu rechnen)."""
    s = speech * (10 ** (speech_dbfs / 20) / active_rms(speech))
    n = noise * (10 ** ((speech_dbfs - snr_db) / 20) / (np.sqrt(np.mean(noise ** 2)) + 1e-12))
    y, sat = soft_limit(s + n)
    return y, {"speech_dbfs": round(speech_dbfs, 1), "noise_dbfs": round(dbfs(n), 1),
               "mix_dbfs": round(dbfs(y), 1), "limited_frac": round(sat, 4)}


def opus_roundtrip(y: np.ndarray, kbps: int) -> np.ndarray:
    """Wie im Browser (MediaRecorder audio/webm;codecs=opus): 48 kHz Opus kodieren und zurück auf 16 kHz."""
    import shutil
    import subprocess
    import tempfile

    import soundfile as sf

    ff = shutil.which("ffmpeg")
    if not ff:
        raise SystemExit("--codec opus braucht ffmpeg im PATH (z. B. pip imageio-ffmpeg, siehe eval_asr.sbatch)")
    with tempfile.TemporaryDirectory() as d:
        src, enc, dst = Path(d) / "in.wav", Path(d) / "x.webm", Path(d) / "out.wav"
        sf.write(str(src), y, SR)
        subprocess.run([ff, "-v", "error", "-y", "-i", str(src), "-ar", "48000", "-c:a", "opus", "-strict", "-2",
                        "-b:a", f"{kbps}k", str(enc)], check=True)
        subprocess.run([ff, "-v", "error", "-y", "-i", str(enc), "-ar", str(SR), "-ac", "1", str(dst)], check=True)
        out, _ = sf.read(str(dst), dtype="float32")
    return out[: len(y)] if len(out) >= len(y) else np.pad(out, (0, len(y) - len(out)))


def find_transcripts(speech_dir: Path, explicit: Optional[str]) -> dict[str, dict]:
    """Zeilen aus transcripts.csv (Downloader, inkl. accent/speaker), gesucht im Sprachordner und zwei Ebenen darüber."""
    cands = [Path(explicit)] if explicit else [d / "transcripts.csv" for d in [speech_dir, *speech_dir.parents[:2]]]
    for c in cands:
        if c.exists():
            with open(c, encoding="utf-8-sig", newline="") as f:
                return {Path(r["file"]).stem: r for r in csv.DictReader(f) if r.get("text")}
    return {}


def rows_from_folder(speech: Path, fixtures: Path, transcripts: Optional[str]) -> list[dict]:
    refs = find_transcripts(speech.resolve(), transcripts)
    rows = []
    for sp in audio_files(speech):
        r = {"id": sp.stem, "file": str(sp)}
        t = refs.get(sp.stem)
        if t:
            r.update({k: v for k, v in t.items() if v not in ("", None) and k not in ("file", "language")})
            r["lang"] = t.get("language") or None
        elif (fixtures / f"{sp.stem}.json").exists():
            fx = json.loads((fixtures / f"{sp.stem}.json").read_text(encoding="utf-8"))
            r.update(text=" ".join(seg["text"] for seg in fx["segments"]), lang=fx.get("language"),
                     text_source="asr_fixture (Silber)")
        rows.append(r)
    return rows


def rows_from_manifest(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("//"):
            r = json.loads(line)
            f = Path(r["file"])
            if not f.is_absolute() and not f.exists():  # relativ zum Manifest
                r["file"] = str(path.parent / f)
            r.setdefault("id", f.stem)
            rows.append(r)
    return rows


def main() -> None:
    import soundfile as sf

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest", type=Path, help="JSONL mit file/text/… (alle Felder werden übernommen)")
    src.add_argument("--speech", type=Path, help="Ordner mit sauberer Sprache (rekursiv)")
    ap.add_argument("--noise", type=Path, default=DEFAULT_NOISE,
                    help=f"Ordner mit echtem Lärm, rekursiv (Standard {DEFAULT_NOISE}; fehlt er → synthetisch)")
    ap.add_argument("--synthetic-noise", action="store_true", help="echten Lärm ignorieren, nur synthetisch")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--snr", nargs="+", type=float, default=None,
                    help="Standard: phone 15 10 5 0 -5 · relative 20 10 5 0")
    ap.add_argument("--level", choices=["phone", "relative"], default="phone",
                    help="phone: Stimme fest laut, Lärm absolut lauter + Limiter (Standard) · relative: altes Verhalten")
    ap.add_argument("--speech-dbfs", type=float, default=-18.0,
                    help="Pegel der aktiven Sprache bei --level phone (Handy direkt vor dem Mund ≈ −20…−14 dBFS)")
    ap.add_argument("--codec", choices=["none", "opus"], default="none",
                    help="opus: wie MediaRecorder im Browser kodieren/dekodieren (braucht ffmpeg)")
    ap.add_argument("--opus-kbps", type=int, default=32)
    ap.add_argument("--langs", nargs="*", default=["de", "en", "pl", "tr"],
                    help="nur Aufnahmen dieser Sprachen (Feld lang); leer = alle")
    ap.add_argument("--noise-only", type=int, default=3, help="reine Lärm-Clips je Lärmklasse (text \"\")")
    ap.add_argument("--silence", type=int, default=3, help="Clips mit fast-Stille (−60 dBFS Rauschen, text \"\")")
    ap.add_argument("--no-clean", dest="clean", action="store_false", help="keine snr_db=clean-Zeilen")
    ap.add_argument("--fixtures", type=Path, default=Path("data/demo/BV-RIEM/fixtures/asr"),
                    help="Referenztexte (ASR-Fixtures) für --speech")
    ap.add_argument("--transcripts", default=None, help="transcripts.csv (Standard: automatisch suchen)")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    a.snr = a.snr or ([15, 10, 5, 0, -5] if a.level == "phone" else [20, 10, 5, 0])
    rng = np.random.default_rng(a.seed)
    a.out.mkdir(parents=True, exist_ok=True)

    bank = NoiseBank(None if a.synthetic_noise else a.noise, rng)
    rows = rows_from_manifest(a.manifest) if a.manifest else rows_from_folder(a.speech, a.fixtures, a.transcripts)
    if a.langs:
        skipped = [r for r in rows if r.get("lang") and r["lang"] not in a.langs]
        rows = [r for r in rows if not r.get("lang") or r["lang"] in a.langs]
        if skipped:
            print(f"{len(skipped)} Aufnahmen in anderen Sprachen übersprungen (--langs {' '.join(a.langs)})")
    print(f"{len(rows)} Sprachdateien · Lärm: {'synthetisch' if bank.synthetic else 'echt'} "
          f"({', '.join(bank.names())})")

    n_out = 0
    with open(a.out / "manifest.jsonl", "w", encoding="utf-8") as man:
        def emit(rec: dict) -> None:
            nonlocal n_out
            man.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_out += 1

        for r in rows:
            s = load(Path(r["file"]))
            if np.max(np.abs(s)) < 1e-4:
                print(f"überspringe {r['id']} (Stille – erst TTS erzeugen: scripts/data/audio/tts_synthesize.py)")
                continue
            if not r.get("text"):
                print(f"warnung: {r['id']} ohne Referenztext")
            base = {k: v for k, v in r.items() if k not in ("snr_db", "noise", "noise_file")}
            # Bootstrap-Cluster: Szenario, sonst Sprecher:in (Common Voice), sonst die saubere Aufnahme selbst –
            # damit alle SNR-Varianten einer Aufnahme im selben Cluster landen
            base.setdefault("scenario_id", r.get("speaker") or r["id"])
            if a.clean:
                if a.level == "phone" or a.codec != "none":  # gleiche Kette ohne Lärm → fairer Vergleich
                    y = s * (10 ** (a.speech_dbfs / 20) / active_rms(s)) if a.level == "phone" else s
                    y, _ = soft_limit(y)
                    y = opus_roundtrip(y, a.opus_kbps) if a.codec == "opus" else y
                    dst = a.out / f"{r['id']}_clean.wav"
                    sf.write(str(dst), y, SR)
                    emit({**base, "id": f"{r['id']}_clean", "file": str(dst), "snr_db": "clean", "noise": None,
                          "clean_file": r["file"], "level": a.level, "codec": a.codec})
                else:
                    emit({**base, "snr_db": "clean", "noise": None, "clean_file": r["file"]})
            for snr in a.snr:
                cls, nfile, nz = bank.sample(len(s))
                tag = f"snr{int(snr)}" if snr >= 0 else f"snrm{int(-snr)}"
                dst = a.out / f"{r['id']}_{tag}.wav"
                if a.level == "phone":
                    y, lv = mix_phone(s, nz, snr, a.speech_dbfs)
                else:
                    y, lv = mix(s, nz, snr), {}
                y = opus_roundtrip(y, a.opus_kbps) if a.codec == "opus" else y
                sf.write(str(dst), y, SR)
                emit({**base, "id": dst.stem, "file": str(dst), "clean_file": r["file"], "snr_db": snr,
                      "noise": cls, "noise_file": nfile, "level": a.level, "codec": a.codec, **lv})
                print(f"{dst.name:44s} SNR {snr:>5} dB  Lärm {cls:28s} {lv.get('noise_dbfs', ''):>6} dBFS"
                      f"  begrenzt {100 * lv.get('limited_frac', 0):.1f} %")

        # Halluzinationstest: reiner Lärm und fast-Stille, 5–15 s, Pegel wie ein typischer Mix
        nod = a.out / "noise_only"
        nod.mkdir(exist_ok=True)
        jobs = [(c, i) for c in bank.names() for i in range(a.noise_only)] + [("silence", i) for i in range(a.silence)]
        for cls, i in jobs:
            n = int(SR * rng.uniform(5, 15))
            if cls == "silence":
                y, nfile = (rng.standard_normal(n) * 10 ** (-60 / 20)).astype(np.float32), "synthetic"
            else:
                _, nfile, y = bank.sample(n, cls)
                y = (y / (np.sqrt(np.mean(y ** 2)) + 1e-9) * 0.05).astype(np.float32)  # ≈ −26 dBFS RMS
                y = y / max(1.0, np.max(np.abs(y)) / 0.98)
            dst = nod / f"noise_{cls}_{i:02d}.wav"
            sf.write(str(dst), y, SR)
            emit({"id": dst.stem, "scenario_id": f"noise_{cls}", "file": str(dst), "text": "", "snr_db": None, "noise": cls, "noise_file": nfile,
                  "split": "dev", "duration_s": round(n / SR, 2)})
    print(f"{n_out} Manifest-Zeilen → {a.out / 'manifest.jsonl'}")


if __name__ == "__main__":
    main()
