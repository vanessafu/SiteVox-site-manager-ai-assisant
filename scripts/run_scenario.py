#!/usr/bin/env python3
"""Einen simulierten Bautag (make_scenario_inputs.py) Ende-zu-Ende durch die Pipeline spielen.

  # 1) Vortag (20.11.) als Historie: Demo-Daten per Fixture-Replay – deterministisch, ohne GPU
  SITEVOX_DATA=data/scenario_runs/X SITEVOX_MODE=demo python scripts/seed_demo.py
  # 2) Szenario-Tag mit echten Modellen (vLLM + ASR) in dieselbe Datenbank
  SITEVOX_DATA=data/scenario_runs/X SITEVOX_MODE=gpu python scripts/run_scenario.py data/raw/scenario_SCN-RIEM-0016_en

Schema 0.3/0.4 (kind "capture" = Fotoserie + eine Notiz) wird so eingespielt, wie es die App erlaubt (ein Foto +
eine Beschreibung je Upload): das ERSTE Foto der Serie mit der Notiz (Text bzw. Sprachaufnahme), die übrigen Fotos
ohne Beschreibung (die Pipeline hängt sie selbst an passende Ereignisse). Folgetage (23.→26.11.) laufen nacheinander
in dieselbe Datenbank, damit "closes"/"continues" über Tage hinweg geprüft werden können.

Die Pipeline bekommt NUR inputs.json (Audio, Notizen, Fotos mit Zufallsnamen + EXIF-Zeit, Bildunterschrift als Antwort
auf die Foto-Rückfrage). gold.json wird hier NICHT gelesen. Ausgabe: <SITEVOX_DATA>/run_output.json für
evaluation/eval_scenario.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sitevox import settings, store  # noqa: E402
from sitevox.drafting import composer  # noqa: E402
from sitevox.pipeline import answer_photo, ingest  # noqa: E402

TZ = "+01:00"
# Vorgänge aus dem Tagesplan des Szenarios, die im Demo-Bauzeitenplan fehlen (Projektwissen, kein Gold-Label)
EXTRA_ACTIVITIES = {
    "A35": {"name": "Abschalung Bodenplatte Achse D", "aliases": ["Abschalung", "Randschalung Achse D",
                                                                   "Edge formwork", "edge formwork axis D"]},
    "A70": {"name": "Montage Fertigteiltreppe TH Nord", "aliases": ["Fertigteiltreppe", "Treppe TH Nord",
                                                                     "precast stair", "prefabricated staircase"]},
}


def ensure_activities(pid: str, day: str, plan: dict | None) -> None:
    have = {a["id"] for a in store.activities(pid)}
    for aid, extra in EXTRA_ACTIVITIES.items():
        if aid in have:
            continue
        unit, target = {"A70": ("Stk", 1)}.get(aid, ("m", 24))
        for a in (plan or {}).get("activities", []):
            if a["id"] == aid:
                unit, target = a["unit"], a["daily_target"]
        store.save_activity(pid, {"id": aid, "name": extra["name"], "start": day, "finish": day, "qty": float(target),
                                  "unit": unit, "lv_pos": "", "lv_sum": 0.0, "preds": [], "aliases": extra["aliases"],
                                  "kind": "task", "duration": 1})
        print(f"Vorgang {aid} ({extra['name']}) ergänzt")


def _replay_capture(pid: str, root: Path, m: dict, ts: str, umeta: dict) -> dict:
    """Erfassung wie in der App: 1. Foto + 1. Notiz als Beschreibung, weitere Fotos ohne Beschreibung, weitere
    Notizen als eigene Nachricht (Text/Sprache) kurz danach. Ohne Foto: jede Notiz als eigene Nachricht."""
    notes = m.get("notes") or [m["note"]]
    key = notes[0]["file"]   # Erfassungs-Schlüssel für die Auswertung (wird der Pipeline nicht übergeben)

    def desc(n: dict) -> dict:
        f = root / n["file"]
        if n["kind"] == "audio":
            return {"mode": "audio", "file": f, "text": None, "language": None}
        return {"mode": "note", "text": f.read_text(encoding="utf-8"), "file": None, "language": None}

    def tag(c: dict, file: str, role: str, note_file: str | None) -> dict:
        c["_file"], c["_role"], c["_note"], c["_key"] = file, role, note_file, key
        return c

    caps, rest = [], list(notes)
    for i, ph in enumerate(m["photos"]):
        d = desc(rest.pop(0)) if i == 0 and rest else {"mode": "none", "text": None, "file": None, "language": None}
        c = ingest(pid, "photo", file=root / ph, captured_at=ts, meta=dict(umeta), prefer_exif_time=True, description=d)
        caps.append(tag(c, ph, "photo+note" if i == 0 else "photo", notes[0]["file"] if i == 0 else None))
    for k, n in enumerate(rest):  # weitere Notizen bzw. Erfassung ohne Foto
        t = ts[:17] + f"{min(59, 20 + 15 * k):02d}" + ts[19:]
        if n["kind"] == "audio":
            c = ingest(pid, "audio", file=root / n["file"], captured_at=t, meta=dict(umeta))
        else:
            c = ingest(pid, "note", text=(root / n["file"]).read_text(encoding="utf-8"), captured_at=t, meta=dict(umeta))
        caps.append(tag(c, n["file"], n["kind"], n["file"]))
    return {"capture_id": caps[0]["capture_id"], "_all": caps}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs_dir", type=Path)
    ap.add_argument("--output-language", default=None, help="de|en (Standard: report_language des Szenarios)")
    ap.add_argument("--plan", type=Path, default=None, help="Szenario-JSON nur für plan_of_day (Vorgänge, kein Gold)")
    ap.add_argument("--no-letters", action="store_true")
    a = ap.parse_args()

    man = json.loads((a.inputs_dir / "inputs.json").read_text(encoding="utf-8"))
    meta, pid, day = man["meta"], man["meta"]["project_id"], man["meta"]["date"]
    out_lang = settings.output_language(a.output_language or meta.get("report_language"))
    plan = json.loads(a.plan.read_text(encoding="utf-8")).get("plan_of_day") if a.plan else None
    ensure_activities(pid, day, plan)
    print(f"Modus {settings.mode()} · ASR {settings.models()['asr']['backend']} · Ausgabesprache {out_lang} · "
          f"{len(man['inputs'])} Eingaben", flush=True)

    log = []
    for m in man["inputs"]:
        f = a.inputs_dir / m.get("file", "")
        ts = f"{day}T{m['time']}:00{TZ}"
        t0 = time.perf_counter()
        umeta = {"source": "mobile", "output_language": out_lang}
        if m["kind"] == "note":
            cap = ingest(pid, "note", text=f.read_text(encoding="utf-8"), captured_at=ts, meta=umeta)
        elif m["kind"] == "audio":
            cap = ingest(pid, "audio", file=f, captured_at=ts, meta=umeta)
        elif m["kind"] == "capture":
            cap = _replay_capture(pid, a.inputs_dir, m, ts, umeta)
        elif m["kind"] == "photo":
            cap = ingest(pid, "photo", file=f, captured_at=ts, meta=umeta, prefer_exif_time=True)
            q = (cap.get("followup") or {}).get("question")
            if m.get("caption"):  # Bildunterschrift des Bauleiters = Antwort auf die Rückfrage
                cap = answer_photo(cap["capture_id"], "note", text=m["caption"], answered_at=ts)
            cap["_question"] = q
        else:
            continue
        dt = time.perf_counter() - t0
        if m["kind"] == "capture":
            for c in cap["_all"]:
                log.append({"file": c["_file"], "kind": c["_role"], "time": m["time"], "capture_id": c["capture_id"],
                            "event_ids": c.get("event_ids", []), "log_ids": c.get("log_ids", []),
                            "note_file": c["_note"], "capture_key": c["_key"], "seconds": round(dt, 1)})
            print(f"{m['time']} serie {cap['_all'][0]['_key']:<30} {len(m['photos'])} Fotos → "
                  f"{[c['capture_id'] for c in cap['_all']]} Ereignisse {sorted({e for c in cap['_all'] for e in c.get('event_ids', [])})}"
                  f" Tagebuch {sum(len(c.get('log_ids') or []) for c in cap['_all'])}  ({dt:.1f}s)", flush=True)
            continue
        log.append({"file": m["file"], "kind": m["kind"], "time": m["time"], "capture_id": cap["capture_id"],
                     "event_ids": cap.get("event_ids", []), "seconds": round(dt, 1)})
        print(f"{m['time']} {m['kind']:<5} {m['file']:<26} → {cap['capture_id']} Ereignisse {cap.get('event_ids')}"
              f"  ({dt:.1f}s)", flush=True)

    # Ereignisse, die heute Belege bekommen haben (inkl. fortgeschriebener Vortagsereignisse)
    caps = {c["capture_id"]: c for c in store.captures(pid, day)}
    touched = {}
    for e in store.events(pid):
        ev_caps = {(store.evidence(x) or {}).get("capture_id") for x in e["evidence"]}
        if e["date"] == day or ev_caps & set(caps):
            touched[e["event_id"]] = e
    letters = []
    if not a.no_letters:
        for e in touched.values():
            if e["recommended_document"].get("requires_letter") and not e.get("letter_id") and e["status"] != "dismissed":
                try:
                    l = composer.create_letter(e["event_id"], actor="scenario", language=out_lang)
                    letters.append(l["letter_id"])
                    print(f"Entwurf {l['letter_id']} ({l['kind']}) für {e['event_id']}", flush=True)
                except ValueError as ex:
                    print(f"kein Entwurf für {e['event_id']}: {ex}")
    touched = {k: store.get("events", k) for k in touched}
    out = {
        "meta": {**meta, "mode": settings.mode(), "asr_backend": settings.models()["asr"]["backend"],
                 "models": {r: settings.models()["llm"][r]["model"] for r in ("extractor", "drafter", "vision")},
                 "output_language": out_lang},
        "inputs": log,
        "captures": [{**{k: c.get(k) for k in ("capture_id", "kind", "captured_at", "file", "event_ids", "summary",
                                                "asr_score", "text", "meta", "log_ids", "logs", "hints")},
                      "transcript_text": (c.get("transcript") or {}).get("text"),
                      "language": (c.get("transcript") or {}).get("language"),
                      "vision": (c.get("vision") or {}).get("analysis"), "followup": c.get("followup"),
                      "answer": c.get("answer")} for c in caps.values()],
        "events": list(touched.values()),
        "evidence_capture": {x: (store.evidence(x) or {}).get("capture_id")
                             for x in {x for e in touched.values() for x in e["evidence"]}
                             | {x for p in store.progress(pid) if p["date"] == day for x in p.get("evidence_ids") or []}
                             | {s.get("evidence_id") for s in store.staffing(pid, day)} - {None}},
        "letters": [store.get("letters", l["letter_id"]) if isinstance(l, dict) else store.get("letters", l)
                    for l in letters],
        "progress": [p for p in store.progress(pid) if p["date"] == day],
        "log_entries": store.log_entries(pid, day),
        "events_all": [{k: e.get(k) for k in ("event_id", "date", "type", "sphere", "status", "start", "end",
                                              "letter_id", "description")} for e in store.events(pid)],
        "letters_all": [{k: l.get(k) for k in ("letter_id", "event_id", "kind", "status", "created_at")}
                        for l in store.query("letters")] if hasattr(store, "query") else [],
        "staffing": store.staffing(pid, day),
    }
    dst = settings.data_dir() / "run_output.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n{len(touched)} Ereignisse, {len(letters)} Entwürfe → {dst}")


if __name__ == "__main__":
    main()
