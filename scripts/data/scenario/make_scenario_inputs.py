#!/usr/bin/env python3
"""Gold-Szenario (data/demo/scenario/scenario_<ID>_<lang>.json) → simulierte Nutzereingaben eines Bautags.

  python scripts/data/scenario/make_scenario_inputs.py data/demo/scenario/scenario_SCN-RIEM-0016_en.json

Ausgabe data/raw/scenario_<ID>_<lang>/  (vorhandenes image/ mit den erzeugten Bildern <IN-xx>.jpg wird gelesen):
  audio/rec_HHMM.wav     Sprachmemo: Sprechform (spoken.py: Uhrzeit/Datum/Dezimal/BA1 ausgeschrieben) → XTTS →
                         ASR-Prüfung (kanonische WER) → Lärm im Handy-Modell (Stimme −18 dBFS, Limiter, Opus).
                         Lauter als im Szenario: SNR + --snr-offset (Standard −5 dB); "clean"-Memos bekommen
                         Hintergrund --clean-bg (Standard Straßenverkehr @ 15 dB).
                         Stimme je Memo: mit --p-accent (Standard 0,6) ein Stimmklon einer Common-Voice-Sprecher:in
                         mit anderer Erstsprache (en/pl/tr-L1, nie die Sprache der Datei), sonst Studio-Stimme.
  notes/note_HHMM.txt    Textnotiz, wörtlich
  photos/IMG_xxxx.jpg    Foto unter ZUFÄLLIGEM Namen + EXIF-Aufnahmezeit/GPS (wie vom Handy) – Dateiname und
                         Reihenfolge verraten weder Eingabe-ID noch Ereignis
  inputs.json            NUR der Eingabestrom (kind, file, time, caption) – das liest die Pipeline
  gold.json              Zuordnung Eingabe/Foto → Gold-Ereignisse – NUR für die Auswertung (eval_scenario.py)

--photo-time exif (Standard): Fotos tragen ihre echte Aufnahmezeit (realistisch, Zeitnähe ist ein legitimes Signal).
--photo-time shuffle: Aufnahmezeiten werden zufällig unter den Fotos vertauscht → Zuordnung nur über Bildinhalt +
                      Bildunterschrift (härterer Test).

Schema 0.3/0.4 ("photo-first", Schlüssel "captures"): jede Erfassung = Fotoserie (1–6 Bilder, auch unbrauchbare)
+ genau EINE Notiz (Text oder Sprache). Ausgabe data/raw/<Dateiname der Szenario-JSON>/ mit
  inputs.json  {"kind": "capture", "time", "photos": [...], "note": {"kind": "text"|"audio", "file"}}
  gold.json    je Erfassung: id, purpose, gold (report/event/action/facts …), Fotos (id, usable, reason)
Bilder: image/<Cxx-Pn>.jpg (fehlende werden übersprungen und in gold.json unter photos_missing vermerkt).
Ton für dieses Schema: Handy direkt am Mund → hohe SNR. Standard --snr-offset +10 (Szenario 0–10 dB → 10–20 dB),
"clean" → Straßenverkehr @ 25 dB. Der Lärm ist absolut trotzdem laut (Stimme fest bei −18 dBFS).
"""
from __future__ import annotations

import argparse
import json
import random
import secrets
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "data" / "audio"))

SR = 16000
SUPPORTED = ("de", "en", "pl", "tr")
VOICE = {"de": "Damien Black", "en": "Damien Black", "pl": "Damien Black", "tr": "Damien Black"}
# Lärmklassen des Szenarios → echte Aufnahmen (data/raw/noise) bzw. synthetisch
NOISE_MAP = {"excavator": ["urbansound8k_engine_idling", "roadwork_open-noise"], "vibrator": ["synthetic:vibrator"],
             "wind": ["synthetic:wind"], "rain": ["synthetic:rain"], "jackhammer": ["urbansound8k_jackhammer"],
             "drilling": ["urbansound8k_drilling"], "traffic": ["street_traffic_DEMAND"]}


def write_exif(src: Path, dst: Path, taken: str, gps: list[float] | None) -> None:
    from PIL import Image

    im = Image.open(src)
    ex = im.getexif()
    dt = taken[:19].replace("-", ":").replace("T", " ")
    ex[0x0132] = dt                                   # DateTime
    exif_ifd = ex.get_ifd(0x8769)
    exif_ifd[0x9003] = dt                             # DateTimeOriginal
    exif_ifd[0x9011] = taken[19:] or "+01:00"         # OffsetTimeOriginal
    if gps:
        def dms(v: float):
            d = int(v)
            m = int((v - d) * 60)
            return (float(d), float(m), round(((v - d) * 60 - m) * 60, 2))
        g = ex.get_ifd(0x8825)
        g[1], g[2], g[3], g[4] = "N", dms(gps[0]), "E", dms(gps[1])
    im.convert("RGB").save(dst, "JPEG", quality=90, exif=ex)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="Standard: data/raw/scenario_<ID>_<lang>")
    ap.add_argument("--photo-time", choices=["exif", "shuffle"], default="exif")
    ap.add_argument("--skip-audio", action="store_true", help="nur Notizen/Fotos/Manifeste (ohne GPU)")
    ap.add_argument("--speech-dbfs", type=float, default=-18.0)
    ap.add_argument("--qc-tries", type=int, default=3)
    ap.add_argument("--seed", type=int, default=16)
    ap.add_argument("--snr-offset", type=float, default=None,
                    help="auf alle Szenario-SNRs addieren (Standard: timeline −5 = lauter, captures +10 = Nahbesprechung)")
    ap.add_argument("--clean-bg", default=None,
                    help="Hintergrund für clean-Memos als KLASSE@SNR ('' = wirklich clean; Standard: timeline "
                         "street_traffic_DEMAND@15, captures street_traffic_DEMAND@25)")
    ap.add_argument("--p-accent", type=float, default=0.6, help="Anteil Memos mit Akzent-Stimmklon")
    ap.add_argument("--clone-from", type=Path, default=ROOT / "data" / "raw" / "speech" / "de_cv")
    a = ap.parse_args()

    sc = json.loads(a.scenario.read_text(encoding="utf-8"))
    lang, sid, day = sc["language"], sc["scenario_id"], sc["meta"]["date"]
    photo_first = "captures" in sc
    if a.snr_offset is None:
        a.snr_offset = 10.0 if photo_first else -5.0
    if a.clean_bg is None:
        a.clean_bg = "street_traffic_DEMAND@25" if photo_first else "street_traffic_DEMAND@15"
    if lang not in SUPPORTED:
        raise SystemExit(f"{a.scenario.name}: Sprache {lang!r} nicht im Umfang (ASR-Spracherkennung nur "
                         f"{'/'.join(SUPPORTED)}) – übersprungen")
    out = a.out or ROOT / "data" / "raw" / (a.scenario.stem if photo_first else f"scenario_{sid}_{lang}")
    if photo_first:
        return main_captures(sc, out, a)
    rng = random.Random(a.seed)
    for d in ("audio", "notes", "photos"):
        shutil.rmtree(out / d, ignore_errors=True)
        (out / d).mkdir(parents=True, exist_ok=True)

    inputs, gold = [], {"scenario_id": sid, "language": lang, "date": day, "inputs": {}, "photos": {},
                        "source": str(a.scenario.relative_to(ROOT) if a.scenario.is_absolute() else a.scenario)}
    voice = [t for t in sc["timeline"] if t["modality"] == "voice"]
    photos = [t for t in sc["timeline"] if t["modality"] == "photo"]

    # ------------------------------------------------------------------ Fotos (zufällige Namen, EXIF-Zeit)
    times = [t["exif"]["datetime"] for t in photos]
    if a.photo_time == "shuffle":
        rng.shuffle(times)
    for t, taken in zip(photos, times):
        src = out / "image" / f"{t['id']}.jpg"
        if not src.exists():  # gleiche Szene in anderer Sprache: Bilder aus einer Schwesterfassung übernehmen
            src = next((p for p in sorted(out.parent.glob(f"scenario_{sid}_*/image/{t['id']}.jpg"))), src)
        if not src.exists():
            print(f"Foto fehlt: {src} – übersprungen")
            continue
        name = f"IMG_{secrets.token_hex(3).upper()}.jpg"
        write_exif(src, out / "photos" / name, taken, t["exif"].get("gps"))
        inputs.append({"kind": "photo", "file": f"photos/{name}", "time": taken[11:16], "caption": t.get("text") or ""})
        gold["photos"][name] = t["id"]
        gold["inputs"][f"photos/{name}"] = {"input_id": t["id"], "events": t["events"]}

    # ------------------------------------------------------------------ Notizen
    for t in sc["timeline"]:
        if t["modality"] == "text":
            f = f"notes/note_{t['time'].replace(':', '')}.txt"
            (out / f).write_text(t["text"], encoding="utf-8")
            inputs.append({"kind": "note", "file": f, "time": t["time"]})
            gold["inputs"][f] = {"input_id": t["id"], "events": t["events"], "text": t["text"]}

    # ------------------------------------------------------------------ Sprachmemos
    for t in voice:
        f = f"audio/rec_{t['time'].replace(':', '')}.wav"
        inputs.append({"kind": "audio", "file": f, "time": t["time"]})
        gold["inputs"][f] = {"input_id": t["id"], "events": t["events"], "text": t["text"], "noise": t["audio"]["noise"],
                             "snr_db": t["audio"]["snr_db"]}
    if not a.skip_audio:
        synth_audio([{"file": f"audio/rec_{t['time'].replace(':', '')}.wav", "text": t["text"],
                      "noise": t["audio"]["noise"], "snr_db": t["audio"]["snr_db"]} for t in voice], out, lang, a, gold)

    inputs.sort(key=lambda x: (x["time"], x["kind"]))
    meta = {"scenario_id": sid, "project_id": sc["meta"]["project_id"], "date": day, "input_language": lang,
            "report_language": sc["meta"].get("report_language", "de-DE")[:2]}
    (out / "inputs.json").write_text(json.dumps({"meta": meta, "inputs": inputs}, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    (out / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(inputs)} Eingaben → {out / 'inputs.json'} (Gold getrennt in gold.json)")


def _find_image(out: Path, sid: str, day: str, pid: str) -> Path | None:
    """image/<Cxx-Pn>.jpg dieser Fassung, sonst aus einer Schwesterfassung (gleiches Szenario + Datum, andere Sprache)."""
    src = out / "image" / f"{pid}.jpg"
    if src.exists():
        return src
    base = out.name.rsplit("_", 1)[0]   # scenario_SCN-RIEM-0016_2026-11-23 (scenario_id im JSON kann abweichen, z. B. 0016P)
    return next(iter(sorted(out.parent.glob(f"{base}_*/image/{pid}.jpg"))), None)


def main_captures(sc: dict, out: Path, a) -> None:
    lang, sid, day = sc["language"], sc["scenario_id"], sc["meta"]["date"]
    for d in ("audio", "notes", "photos"):
        shutil.rmtree(out / d, ignore_errors=True)
        (out / d).mkdir(parents=True, exist_ok=True)
    gps = ((sc.get("meta") or {}).get("gps")) or [48.1372, 11.6915]   # Messestadt Riem
    inputs, voice = [], []
    gold = {"schema": sc.get("schema_version"), "scenario_id": sid, "language": lang, "date": day,
            "source": str(a.scenario), "captures": {}, "photos": {}, "inputs": {}, "photos_missing": []}
    for c in sc["captures"]:
        hh = c["time"].replace(":", "")
        photos, gphotos = [], []
        for i, p in enumerate(c["photos"]):
            gp = {"id": p["id"], "usable": p.get("usable", True), "reason": p.get("reason")}
            src = _find_image(out, sid, day, p["id"])
            if not src:
                gold["photos_missing"].append(p["id"])
                gphotos.append({**gp, "file": None})
                continue
            name = f"IMG_{secrets.token_hex(3).upper()}.jpg"
            taken = f"{day}T{c['time']}:{min(59, 4 + 9 * i):02d}+01:00"   # Serie: Bilder im Abstand weniger Sekunden
            write_exif(src, out / "photos" / name, taken, gps)
            photos.append(f"photos/{name}")
            gold["photos"][name] = p["id"]
            gphotos.append({**gp, "file": f"photos/{name}"})
        # Schema 0.3/0.4: genau eine "note"; 0.5: "notes" = 1–2 Notizen (mehrere Nachrichten kurz hintereinander)
        notes_in = c.get("notes") or [c["note"]]
        au = c.get("audio") or {}
        notes = []
        for k, n in enumerate(notes_in):
            suf = f"_{k + 1}" if len(notes_in) > 1 else ""
            if n["kind"] == "voice":
                nf = f"audio/rec_{hh}_{c['id']}{suf}.wav"
                voice.append({"file": nf, "text": n["text"], "noise": au.get("noise", "clean"), "snr_db": au.get("snr_db")})
                gold["inputs"][nf] = {"capture": c["id"], "text": n["text"], "noise": au.get("noise", "clean"),
                                      "snr_db": au.get("snr_db")}
                notes.append({"kind": "audio", "file": nf})
            else:
                nf = f"notes/note_{hh}_{c['id']}{suf}.txt"
                (out / nf).write_text(n["text"], encoding="utf-8")
                gold["inputs"][nf] = {"capture": c["id"], "text": n["text"]}
                notes.append({"kind": "text", "file": nf})
        inputs.append({"kind": "capture", "time": c["time"], "photos": photos, "notes": notes})
        gold["captures"][c["id"]] = {"time": c["time"], "purpose": c.get("purpose"),
                                     "note_kind": "+".join(n["kind"] for n in notes_in),
                                     "note_file": notes[0]["file"], "note_files": [n["file"] for n in notes],
                                     "photos": gphotos, "gold": c.get("gold") or {}}
    if not a.skip_audio and voice:
        synth_audio(voice, out, lang, a, gold)
    inputs.sort(key=lambda x: x["time"])
    meta = {"scenario_id": sid, "project_id": sc["meta"]["project_id"], "date": day, "input_language": lang,
            "report_language": sc["meta"].get("report_language", "de-DE")[:2], "schema": sc.get("schema_version")}
    (out / "inputs.json").write_text(json.dumps({"meta": meta, "inputs": inputs}, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    (out / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8")
    n_ph = sum(len(i["photos"]) for i in inputs)
    print(f"{len(inputs)} Erfassungen · {n_ph} Fotos ({len(gold['photos_missing'])} fehlen: "
          f"{', '.join(gold['photos_missing']) or '–'}) · {len(voice)} Sprachnotizen → {out / 'inputs.json'}")


def synth_audio(items: list[dict], out: Path, lang: str, a, gold: dict) -> None:
    """items: [{"file", "text", "noise", "snr_db"}]; schreibt Messwerte nach gold["inputs"][file]."""
    import soundfile as sf
    import torch
    from spoken import spoken_form
    from sythesize_noise_data import NoiseBank, active_rms, mix_phone, opus_roundtrip, soft_limit, synthetic_noise
    from tts_synthesize import QC, clone_speakers, load_tts, synth_checked

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tts = load_tts(dev)
    qc = QC("medium", max_ins=0.15, max_wer=0.5)
    bank = NoiseBank(ROOT / "data" / "raw" / "noise", np.random.default_rng(a.seed))
    rng = np.random.default_rng(a.seed)
    native = {"kind": "builtin", "name": VOICE.get(lang, "Damien Black"), "accent": f"{lang}-tts"}
    clones = [c for c in (clone_speakers(a.clone_from, 3, {"en-L1", "pl-L1", "tr-L1"}) if a.clone_from.exists() else [])
              if not c["accent"].startswith(lang + "-")]
    for c in clones:
        c.pop("only_lang", None)
    print(f"Stimmen: Studio {native['name']} + {len(clones)} Akzent-Klone "
          f"({', '.join(c['accent'] for c in clones)}), p_accent={a.p_accent}", flush=True)
    for t in items:
        f = t["file"]
        spk = clones[rng.integers(len(clones))] if clones and rng.random() < a.p_accent else native
        spoken = spoken_form(t["text"], lang)
        y, info = synth_checked(tts, qc, spoken, t["text"], lang, spk, a.qc_tries)
        noise, snr = t["noise"], t["snr_db"]
        if noise == "clean" or snr is None:
            if a.clean_bg:
                noise, snr = a.clean_bg.split("@")[0], float(a.clean_bg.split("@")[1])
            else:
                y, _ = soft_limit(y * (10 ** (a.speech_dbfs / 20) / active_rms(y)))
        else:
            snr = float(snr) + a.snr_offset
        if noise != "clean" and snr is not None:
            cls = noise if noise in bank.classes else rng.choice(NOISE_MAP.get(noise, [f"synthetic:{noise}"]))
            if cls.startswith("synthetic:") or cls not in bank.classes:
                nz, src = synthetic_noise(len(y), rng, cls.split(":")[-1] if ":" in cls else "engine"), cls
            else:
                _, nfile, nz = bank.sample(len(y), cls)
                src = f"{cls}/{nfile}"
            y, _ = mix_phone(y, nz, float(snr), a.speech_dbfs)
        else:
            src = "clean"
        y = opus_roundtrip(y, 32)
        sf.write(str(out / f), y, SR, subtype="PCM_16")
        gold["inputs"][f].update({"noise_used": noise, "snr_used": snr, "noise_source": src, "spoken": spoken,
                                  "voice": f"{spk['kind']}:{spk['name']}", "accent": spk["accent"],
                                  "duration_s": round(len(y) / SR, 2),
                                  **{k: v for k, v in info.items() if k != "qc_hyp"}})
        print(f"{f:24s} {len(y) / SR:5.1f}s  {spk['accent']:12s} {noise}@{snr}  QC WER {info.get('qc_wer')} "
              f"ins {info.get('qc_ins')} ×{info.get('qc_tries')}"
              f"{'' if info.get('qc_pass') else '  (QC NICHT bestanden – bester Versuch)'}", flush=True)


if __name__ == "__main__":
    main()
