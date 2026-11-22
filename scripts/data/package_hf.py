#!/usr/bin/env python3
"""Szenario-Datensatz für Hugging Face lokal zusammenstellen (kein Upload).

  python scripts/data/package_hf.py                       # → data/hf_release/sitevox-scenarios/
  python scripts/data/package_hf.py --out /pfad --langs de en pl tr

Inhalt
  project/            Projektunterlagen des fiktiven BV Riem: Bauvertrag, LV, Planlieferliste, Besprechungsprotokoll,
                      Bauzeitenplan (xlsx), Leistungshistorie, Stammdaten (project.yaml aus config/baseline.yaml)
  project/day0_2026-11-20/  Vortag als Historie: Sprachmemos, Fotos, E-Mails (.eml) + inputs.json
  scenarios/          Gold-Szenarien (JSON) je Tag × Sprache
  images/<Tag>/       Originalbilder je Erfassungsfoto (<Cxx-Pn>.jpg), sprachunabhängig
  inputs/<Szenario>/  Eingabestrom wie ihn das System sieht: audio/, notes/, photos/ (Zufallsnamen + EXIF),
                      inputs.json, gold.json (Zuordnung + Audio-Metadaten)
  manifest.csv        jede Datei mit Größe und SHA-256
  README.md           Dataset Card (Englisch)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "data" / "demo"
RAW = ROOT / "data" / "raw"


def copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "hf_release" / "sitevox-scenarios")
    ap.add_argument("--langs", nargs="+", default=["de", "en", "pl", "tr"])
    ap.add_argument("--project", default="BV-RIEM")
    ap.add_argument("--license", default="cc-by-nc-sa-4.0")
    a = ap.parse_args()
    out = a.out
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    stats = Counter()
    notes = []

    # ------------------------------------------------------------------ Projektunterlagen
    pdir = DEMO / a.project
    for sub in ("docs", "plan", "history"):
        for f in sorted((pdir / sub).glob("*")):
            if f.is_file():
                copy(f, out / "project" / sub / f.name)
                stats["project_docs"] += 1
    base = yaml.safe_load((ROOT / "config" / "baseline.yaml").read_text(encoding="utf-8"))
    proj = next(p for p in base["projects"] if p["id"] == a.project)
    (out / "project" / "project.yaml").write_text(yaml.safe_dump(proj, allow_unicode=True, sort_keys=False),
                                                   encoding="utf-8")
    day0 = sorted((pdir / "inputs").glob("*.json"))
    for j in day0:
        d = out / "project" / f"day0_{j.stem}"
        items = json.loads(j.read_text(encoding="utf-8"))
        for it in items:
            it.pop("fixture", None)   # Demo-Replay-Schlüssel, für Nutzer des Datensatzes ohne Bedeutung
            src = pdir / "inputs" / j.stem / it["file"]
            if src.exists():
                copy(src, d / it["file"])
                stats[f"day0_{it['kind']}"] += 1
        (d / "inputs.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    # ------------------------------------------------------------------ Szenarien, Bilder, Eingaben
    scen = sorted(p for p in (DEMO / "scenario").glob("scenario_SCN-*_2026-*_*.json")
                  if p.stem.rsplit("_", 1)[1] in a.langs)
    days = {}
    for sc in scen:
        copy(sc, out / "scenarios" / sc.name)
        stats["scenarios"] += 1
        base_name = sc.stem.rsplit("_", 1)[0]          # scenario_SCN-RIEM-0016_2026-11-23
        day_key = base_name.removeprefix("scenario_")
        days.setdefault(day_key, json.loads(sc.read_text(encoding="utf-8")))
        inp = RAW / sc.stem
        if not (inp / "inputs.json").exists():
            notes.append(f"{sc.stem}: no generated inputs")
            continue
        for sub in ("audio", "notes", "photos"):
            for f in sorted((inp / sub).glob("*")):
                copy(f, out / "inputs" / sc.stem / sub / f.name)
                stats[f"inputs_{sub}"] += 1
        for f in ("inputs.json", "gold.json"):
            g = json.loads((inp / f).read_text(encoding="utf-8"))
            if f == "gold.json":
                g["source"] = f"scenarios/{sc.name}"
                for v in g.get("inputs", {}).values():
                    if not v.get("qc_pass", True):
                        notes.append(f"{sc.stem}/{v.get('capture')}: TTS quality check failed (best attempt kept)")
            (out / "inputs" / sc.stem / f).write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    for day_key, s in days.items():
        ids = [p["id"] for c in s["captures"] for p in c["photos"]]
        src_dirs = sorted(RAW.glob(f"scenario_{day_key}_*/image"))
        missing = []
        for pid in ids:
            f = next((d / f"{pid}.jpg" for d in src_dirs if (d / f"{pid}.jpg").exists()), None)
            if f:
                copy(f, out / "images" / day_key / f.name)
                stats["images"] += 1
            else:
                missing.append(pid)
        if missing:
            notes.append(f"{day_key}: {len(missing)}/{len(ids)} images not yet available ({', '.join(missing)})")

    # ------------------------------------------------------------------ Manifest + README
    (out / "README.md").write_text(readme(a, days, stats, notes), encoding="utf-8")
    rows = []
    for f in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "manifest.csv"):
        rows.append({"path": str(f.relative_to(out)), "bytes": f.stat().st_size,
                     "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["path", "bytes", "sha256"])
        w.writeheader()
        w.writerows(rows)
    size = sum(r["bytes"] for r in rows) / 1e6
    print(f"{len(rows)} Dateien, {size:.0f} MB → {out}")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    for n in notes:
        print("  !", n)


def readme(a, days: dict, stats: Counter, notes: list[str]) -> str:
    day_rows = "\n".join(
        f"| {k.split('_')[1]} | {s['meta'].get('weekday', '')} | {len(s['captures'])} | "
        f"{sum(len(c['photos']) for c in s['captures'])} | {sum(n.get('kind') == 'voice' for c in s['captures'] for n in (c.get('notes') or [c['note']] if c.get('note') else c.get('notes') or []))} | "
        f"{sum(bool((c.get('gold') or {}).get('event')) for c in s['captures'])} | {s.get('title', '')} |"
        for k, s in sorted(days.items()))
    known = "\n".join(f"- {n}" for n in notes) or "- none"
    return f"""---
license: {a.license}
language: [{', '.join(a.langs)}]
pretty_name: SiteVox Construction-Site Scenarios
task_categories: [automatic-speech-recognition, image-to-text, text-generation, text-classification]
tags: [construction, site-management, multimodal, synthetic, speech, noise, VOB/B, german-construction-law]
size_categories: [n<1K]
---

# SiteVox Construction-Site Scenarios

A small, fully **synthetic**, multimodal benchmark of a German building site seen through the phone of the
contractor's site manager. Over four consecutive working days (23–26 Nov 2026) the site manager photographs what
happens and adds one or two short notes per capture (with 0–2 photos), typed or spoken, in **German, English, Polish or Turkish**.
Every capture is annotated with what a good assistant should do with it: write a site-diary entry, recognise a
disruption, attribute it to the right risk sphere under the German construction contract rules (VOB/B), draft
the right notice to the right recipient, attach the right photos, and do none of this for routine messages.

The dataset was built to evaluate the SiteVox pipeline end to end (speech recognition → information extraction →
rules → letter drafting, with a vision-language model for photos). It can also be used on its own for
noisy multilingual ASR on domain speech, photo triage, site-diary extraction and event/notice classification.

> All people, companies, addresses, e-mail addresses (`*.example`) and documents are fictional.
> Voices are synthetic. Do not use this data to make real legal decisions.

## Contents

| Day | Weekday | Captures | Photos | Voice notes | Gold events | Title |
|---|---|---|---|---|---|---|
{day_rows}

Each day exists in {len(a.langs)} language versions ({', '.join(a.langs)}). Gold annotations are identical across
languages; only the site manager's notes differ. Outgoing letters are always expected in German.

```
project/                      the fictional project "BV Riem, Baufeld 3"
  docs/                         construction contract, bill of quantities (LV), plan delivery list, meeting minutes
  plan/Bauzeitenplan.xlsx       construction schedule
  history/leistung.csv          progress history before the scenario days
  project.yaml                  master data: client, representative, crews, equipment, contacts
  day0_2026-11-20/              the preceding day as history: voice memos, photos, two incoming e-mails (.eml)
scenarios/                    gold scenario per day × language (JSON, schema "gold-scenario/0.3–0.4")
images/<day>/<Cxx-Pn>.jpg     original image of every photo in the scenario, language-independent
inputs/<scenario>/            the input stream exactly as the system receives it
  audio/rec_HHMM_Cxx.wav        voice notes (16 kHz mono)
  notes/note_HHMM_Cxx.txt       typed notes
  photos/IMG_xxxxxx.jpg         the same images under random names with EXIF time and GPS
  inputs.json                   ordered captures: time, photos, notes[] (text or audio)
  gold.json                     mapping of inputs to gold captures + audio metadata (SNR, noise, accent, TTS QC)
manifest.csv                  every file with size and SHA-256
```

Photo names and order do not reveal which event a photo belongs to; the mapping is only in `gold.json`.
Use `inputs/` for blind evaluation and `scenarios/` + `gold.json` only for scoring.

### Scenario JSON (one capture)

```json
{{"id": "C04", "time": "09:35", "purpose": "equipment",
 "audio": {{"noise": "excavator", "snr_db": 5}},
 "photos": [{{"id": "C04-P2", "scene_en": "Soldier-pile wall with two bays without timber lagging", "usable": true}},
            {{"id": "C04-P4", "scene_en": "Blurred ground", "usable": false, "reason": "blurry"}}],
 "note": {{"kind": "voice", "language": "de", "text": "Also, Bagger steht seit 09:30, der Maier ist mit dem Verbau …"}},
 "gold": {{"report": ["3_geraete", "6_vorkommnisse", "7_foto"],
          "event": {{"id": "EVT-01", "type": "third_party_interference", "sphere": "AG",
                    "document": {{"type": "Behinderungsanzeige", "basis": ["§ 6 Abs. 1 VOB/B"]}}}},
          "action": {{"type": "email", "to": "AG-VERTRETER", "attach": ["C04-P1", "C04-P2", "C04-P3"],
                     "must_include": ["Achse 4", "2 Felder", "seit 09:30"], "must_not": ["Weisung an Maier"]}}}}}}
```

Each scenario also contains the day plan, the party registry (who is contracted by whom, which decides the
recipient and the risk sphere), the weather ground truth and an `expected_report` (staffing, equipment hours,
deliveries, daily output per activity, incidents, selected photos, expected and forbidden messages).
Routine captures carry `facts` and sometimes a `near_miss` (e.g. "excavator running, new hose holds"), which
must **not** become an incident. Later days continue or close events of earlier days (`continues`, `closes`).

## How the audio was made

1. The written note is converted to its spoken form (times, dates, decimals and codes spelled out per language).
2. Speech synthesis with XTTS-v2. About 60 % of the notes use a voice cloned from a Common Voice speaker with a
   different first language (English, Polish or Turkish L1), the rest a built-in voice.
3. Automatic quality check: the synthesized audio is transcribed with Whisper (medium); up to three attempts.
4. Phone close-talk mixing: speech fixed at −18 dBFS active level, real or synthetic construction noise
   (excavator, vibrator, wind, rain, traffic) added at the scenario SNR **+10 dB** (effective 10–20 dB;
   "clean" notes get street traffic at 25 dB), soft limiter, Opus 32 kbit/s round trip (as in a browser upload).

Per-file SNR, noise source, voice/accent and QC result are in `inputs/<scenario>/gold.json`.

## Known limitations

- Synthetic speech and generated images; real site recordings differ (reverberation, overlapping talk, dialects).
- One fictional project, four days, about 40 captures per language: suited for evaluation and error analysis,
  not for training.
- Gold labels were written by one annotator with construction-law background knowledge; they reflect one
  reasonable reading of VOB/B, not legal advice.
{known}

## Licence and attribution

Released under **{a.license.upper()}** (attribution, non-commercial, share-alike): non-commercial because of XTTS-v2 and
UrbanSound8K, share-alike because of DEMAND. The dataset contains derivatives of:

- **XTTS-v2** (Coqui, Coqui Public Model License 1.0.0, non-commercial; https://coqui.ai/cpml) – all synthetic speech
- **Common Voice** (CC0) – reference clips for voice cloning
- **UrbanSound8K** (CC BY-NC 3.0, J. Salamon, C. Jacoby, J. P. Bello, ACM MM 2014) – engine, jackhammer, drilling noise
- **DEMAND** (CC BY-SA 3.0, J. Thiemann, N. Ito, E. Vincent, "The Diverse Environments Multi-channel Acoustic Noise
  Database", ICA 2013, https://zenodo.org/records/1227121) – street traffic background, mixed into the audio
- Images: generated with an image model; scenario texts, documents and annotations: original work of Zitong Fu.

Note: CC BY-SA 3.0 (DEMAND) and the non-commercial terms above are not formally fully compatible; the dataset is
offered for non-commercial research only, with all upstream licences and attributions kept. Commercial users must
replace the synthetic speech and noise.

## Citation

```bibtex
@misc{{sitevox_scenarios_2026,
  author = {{Fu, Zitong}},
  title  = {{SiteVox Construction-Site Scenarios: a multilingual, multimodal benchmark for construction site
            documentation under VOB/B}},
  year   = {{2026}},
  howpublished = {{https://huggingface.co/datasets/vanessaaaa1224/sitevox-scenarios}},
  note   = {{Synthetic dataset}}
}}
```
"""


if __name__ == "__main__":
    main()
