#!/usr/bin/env python3
"""TTS-Sprachaufnahmen für die ASR-Evaluation (nur DEV!) und für die Demo – XTTS-v2 (coqui-tts), de/en/tr/pl.

Sprecher:innen
  builtin   XTTS-Studio-Stimmen (Standard: 1 weiblich + 1 männlich), sprechen jede Sprache "neutral".
  clone     Stimmklon aus echten Common-Voice-Aufnahmen mit L2-Akzent (download_data.py → data/raw/speech/de_cv),
            je Akzent eine Sprecher:in. Nur für deutsche Texte. ACHTUNG: ein Klon überträgt Stimmfarbe und etwas
            Prosodie, aber kaum Lautfehler – accent="pl-L1-clone" ist eine Annäherung, kein echter Akzent.
            Für akzentbezogene Aussagen die echten CV-Clips verwenden (die sind auch test-tauglich).

  # Szenarien → data/asr_eval/clean/*.wav + manifest.jsonl (Eingabe für sythesize_noise_data.py --manifest)
  python scripts/data/audio/tts_synthesize.py --scenarios evaluation/data/scenarios.jsonl \
      --clone-from data/raw/speech/de_cv --out data/asr_eval/clean
  # Demo-Memos (scripts/make_demo_data.py: MEMOS) mit echter Stimme überschreiben, danach make_demo_data.py erneut
  python scripts/data/audio/tts_synthesize.py --demo
  # Nur Gewichte laden (Login-Knoten mit Internet), danach offline im GPU-Job
  python scripts/data/audio/tts_synthesize.py --prefetch

Szenario-Feld "text_tts" (optional) überschreibt den gesprochenen Text (z. B. "zehn Uhr zwei" statt "10:02");
die Referenz im Manifest bleibt "text". Ausgabe 16 kHz mono PCM16. XTTS-Lizenz: Coqui Public Model License
(nicht-kommerziell) → nur für Forschung/Evaluation; COQUI_TOS_AGREED=1 wird gesetzt.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SR = 16000
MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
XTTS_LANGS = {"de", "en", "tr", "pl", "es", "fr", "it", "pt", "ru", "nl", "cs", "ar", "zh-cn", "hu", "ko", "ja", "hi"}
BUILTIN = ["Ana Florence", "Damien Black"]  # w / m
DEMO_SPEAKER = "Damien Black"


def load_tts(device: str):
    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    from TTS.api import TTS

    return TTS(MODEL, progress_bar=False).to(device)


def to16k(wav, sr: int) -> np.ndarray:
    import librosa

    y = np.asarray(wav, dtype=np.float32)
    y = librosa.resample(y, orig_sr=sr, target_sr=SR) if sr != SR else y
    return y / max(1.0, float(np.max(np.abs(y))) / 0.95)


def synth(tts, text: str, lang: str, spk: dict, seed: int = 0, temperature: float = 0.75) -> np.ndarray:
    import torch

    torch.manual_seed(seed)
    kw = {"speaker_wav": spk["ref"]} if spk["kind"] == "clone" else {"speaker": spk["name"]}
    wav = tts.tts(text=text, language=lang, split_sentences=True, temperature=temperature, **kw)
    return to16k(wav, tts.synthesizer.output_sample_rate)


class QC:
    """Prüft jede TTS-Aufnahme mit einer UNABHÄNGIGEN, kleineren ASR (faster-whisper medium, Sprache fest, ohne
    Fachbegriff-Prompt). XTTS erzeugt v. a. bei kurzen Sätzen/Stimmklonen Lautbrei am Ende → als Einfügungen sichtbar.
    Verworfen wird bei Einfügungsquote > max_ins oder WER > max_wer; dann neuer Seed + niedrigere Temperatur."""

    def __init__(self, model: str, max_ins: float, max_wer: float):
        import torch
        from faster_whisper import WhisperModel

        sys.path.insert(0, str(ROOT))
        from evaluation import metrics as M

        self.M, self.max_ins, self.max_wer = M, max_ins, max_wer
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        if dev == "cuda":  # cuBLAS/cuDNN über torch in den Prozess laden (CTranslate2 findet sie sonst nicht)
            torch.zeros(1, device="cuda") @ torch.zeros(1, device="cuda")
        self.model = WhisperModel(model, device=dev, compute_type="float16" if dev == "cuda" else "int8")

    def check(self, y: np.ndarray, ref: str, lang: str) -> dict:
        segs, _ = self.model.transcribe(y, language=lang, beam_size=5, vad_filter=False,
                                        condition_on_previous_text=False)
        hyp = " ".join(s.text.strip() for s in segs)
        w = self.M.wer_counts(self.M.canonical(ref), self.M.canonical(hyp))  # Formatierung ≠ Fehler
        n = max(1, w["n_ref"])
        r = {"qc_hyp": hyp, "qc_wer": round(w["errors"] / n, 3), "qc_ins": round(w["ins"] / n, 3)}
        r["qc_pass"] = r["qc_ins"] <= self.max_ins and r["qc_wer"] <= self.max_wer
        return r


def synth_checked(tts, qc: "QC | None", text: str, ref: str, lang: str, spk: dict, tries: int):
    """→ (Audio, QC-Info). Bester Versuch (wenigste Einfügungen) wird behalten, auch wenn keiner besteht."""
    best = None
    for k in range(tries if qc else 1):
        y = synth(tts, text, lang, spk, seed=k, temperature=max(0.45, 0.75 - 0.15 * k))
        if qc is None:
            return y, {}
        info = qc.check(y, ref, lang) | {"qc_tries": k + 1}
        if best is None or (info["qc_ins"], info["qc_wer"]) < (best[1]["qc_ins"], best[1]["qc_wer"]):
            best = (y, info)
        if info["qc_pass"]:
            break
    return best


def clone_speakers(folder: Path, per_accent: int, accents: set[str] | None) -> list[dict]:
    """Je Akzent die Sprecher:innen mit der meisten Audiodauer; Referenz = bis zu 3 Clips (XTTS: 6–30 s ideal)."""
    tr = next((p for p in [folder / "transcripts.csv", *[d / "transcripts.csv" for d in folder.parents[:2]]]
               if p.exists()), None)
    if tr is None:
        sys.exit(f"transcripts.csv zu {folder} nicht gefunden – erst download_data.py laufen lassen")
    by_spk: dict[str, dict] = {}
    with open(tr, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            acc, spk = r.get("accent"), r.get("speaker")
            if not acc or not spk or acc == "de-L1" or (accents and acc not in accents):
                continue
            p = ROOT / "data" / "raw" / r["file"] if not Path(r["file"]).is_absolute() else Path(r["file"])
            p = p if p.exists() else tr.parent / r["file"]
            d = by_spk.setdefault(spk, {"accent": acc, "clips": [], "secs": 0.0, "gender": r.get("gender", "")})
            d["clips"].append(str(p))
            d["secs"] += float(r.get("seconds") or 0)
    out, per = [], {}
    for spk, d in sorted(by_spk.items(), key=lambda kv: -kv[1]["secs"]):
        if per.get(d["accent"], 0) >= per_accent:
            continue
        per[d["accent"]] = per.get(d["accent"], 0) + 1
        out.append({"kind": "clone", "name": spk, "accent": f"{d['accent']}-clone", "ref": d["clips"][:3],
                    "gender": d["gender"], "only_lang": "de"})
    return out


def load_scenarios(path: Path, all_sources: bool, langs: set[str] | None) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        r = json.loads(line)
        if (all_sources or r.get("source") == "audio") and (not langs or r["lang"] in langs):
            rows.append(r)
    return rows


def run_scenarios(a, tts) -> None:
    import soundfile as sf

    rows = load_scenarios(a.scenarios, a.all_sources, set(a.langs) if a.langs else None)
    speakers = [{"kind": "builtin", "name": n, "accent": "tts"} for n in a.builtin]
    if a.clone_from:
        speakers += clone_speakers(a.clone_from, a.clones_per_accent, set(a.accents) if a.accents else None)
    a.out.mkdir(parents=True, exist_ok=True)
    print(f"{len(rows)} Szenario-Varianten × {len(speakers)} Stimmen "
          f"({', '.join(s['name'] + '/' + s['accent'] for s in speakers)})", flush=True)
    n = n_drop = 0
    qc = QC(a.qc_model, a.qc_max_ins, a.qc_max_wer) if a.qc_model else None
    with open(a.out / "manifest.jsonl", "w", encoding="utf-8") as man:
        for r in rows:
            if r["lang"] not in XTTS_LANGS:
                print(f"überspringe {r['id']}: Sprache {r['lang']} nicht in XTTS")
                continue
            for i, spk in enumerate(speakers):
                if spk.get("only_lang") and spk["only_lang"] != r["lang"]:
                    continue
                tag = f"tts{i}" if spk["kind"] == "builtin" else f"cl_{spk['accent'].split('-')[0]}"
                rid = f"{r['id'].replace('-', '_')}_{tag}"
                dst = a.out / f"{rid}.wav"
                spoken = r.get("text_tts") or r["text"]
                info = {}
                if not (a.skip_existing and dst.exists()):
                    y, info = synth_checked(tts, qc, spoken, r["text"], r["lang"], spk, a.qc_tries)
                    if qc and not info["qc_pass"] and a.qc_drop:
                        n_drop += 1
                        print(f"{rid:32s} VERWORFEN nach {info['qc_tries']} Versuchen (Einfügungen "
                              f"{info['qc_ins']:.0%}, WER {info['qc_wer']:.0%}): {info['qc_hyp'][:70]}", flush=True)
                        continue
                    sf.write(str(dst), y, SR, subtype="PCM_16")
                dur = sf.info(str(dst)).duration
                rec = {"id": rid, "file": str(dst), "text": r["text"], "scenario_id": r["scenario_id"],
                       "variant_id": r["id"], "pair_id": r.get("pair_id"), "lang": r["lang"],
                       "speaker": f"{spk['kind']}:{spk['name']}", "accent": spk["accent"],
                       "tts_model": "xtts_v2", "split": "dev", "duration_s": round(dur, 2)}
                if spoken != r["text"]:
                    rec["text_tts"] = spoken
                rec.update({k: v for k, v in info.items() if k != "qc_hyp"})
                man.write(json.dumps(rec, ensure_ascii=False) + "\n")
                man.flush()
                n += 1
                q = f"  QC WER {info['qc_wer']:.0%} ins {info['qc_ins']:.0%} ×{info['qc_tries']}" if info else ""
                print(f"{rid:32s} {dur:5.1f}s  {spk['name']}{q}", flush=True)
    print(f"{n} Aufnahmen → {a.out / 'manifest.jsonl'}" + (f" ({n_drop} verworfen)" if qc else ""))


def run_demo(a, tts) -> None:
    import soundfile as sf

    sys.path.insert(0, str(ROOT / "scripts"))
    from make_demo_data import INP, MEMOS  # noqa: E402

    INP.mkdir(parents=True, exist_ok=True)
    spk = {"kind": "builtin", "name": a.demo_speaker}
    for key, (_, text) in MEMOS.items():
        y = synth(tts, text, "de", spk)
        sf.write(str(INP / f"{key}.wav"), y, SR, subtype="PCM_16")
        print(f"{key}.wav  {len(y) / SR:5.1f}s  {a.demo_speaker}", flush=True)
    print(f"Demo-Memos geschrieben nach {INP}. Jetzt: python scripts/make_demo_data.py "
          "(behält echte Audiodateien, passt ASR-Fixture-Zeiten an)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scenarios", type=Path, help="scenarios.jsonl (Format: evaluation/README.md)")
    mode.add_argument("--demo", action="store_true", help="MEMOS aus make_demo_data.py vertonen")
    mode.add_argument("--prefetch", action="store_true", help="nur Modell herunterladen")
    mode.add_argument("--list-speakers", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "asr_eval" / "clean")
    ap.add_argument("--builtin", nargs="*", default=BUILTIN, help="XTTS-Studio-Stimmen (leer = keine)")
    ap.add_argument("--clone-from", type=Path, default=None, help="Ordner mit CV-Akzent-Clips (data/raw/speech/de_cv)")
    ap.add_argument("--clones-per-accent", type=int, default=2)
    ap.add_argument("--accents", nargs="*", default=["en-L1", "pl-L1", "tr-L1"],
                    help="Akzente der Stimmklone (Erstsprache der CV-Sprecher:in)")
    ap.add_argument("--langs", nargs="*", default=None, help="nur diese Szenario-Sprachen")
    ap.add_argument("--all-sources", action="store_true", help="auch source=note/email vertonen")
    ap.add_argument("--demo-speaker", default=DEMO_SPEAKER)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--qc-model", default="medium", help="faster-whisper-Modell für die TTS-Prüfung ('' = aus)")
    ap.add_argument("--qc-tries", type=int, default=3)
    ap.add_argument("--qc-max-ins", type=float, default=0.15, help="max. Einfügungen / Referenzwörter")
    ap.add_argument("--qc-max-wer", type=float, default=0.5)
    ap.add_argument("--qc-keep", dest="qc_drop", action="store_false",
                    help="nicht bestandene Aufnahmen behalten (bester Versuch) statt verwerfen")
    ap.add_argument("--device", default=None, help="cuda|cpu (Standard: cuda, falls verfügbar)")
    a = ap.parse_args()

    import torch

    device = a.device or ("cuda" if torch.cuda.is_available() else "cpu")
    tts = load_tts("cpu" if a.prefetch else device)
    if a.prefetch:
        print("XTTS-v2 im Cache:", os.environ.get("TTS_HOME", "~/.local/share/tts"))
        return
    if a.list_speakers:
        print("\n".join(tts.speakers or []))
        return
    print(f"XTTS-v2 auf {device}" + (f" ({torch.cuda.get_device_name()})" if device == "cuda" else ""), flush=True)
    run_demo(a, tts) if a.demo else run_scenarios(a, tts)


if __name__ == "__main__":
    main()
