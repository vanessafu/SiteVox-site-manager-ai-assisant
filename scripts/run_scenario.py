#!/usr/bin/env python3
"""Einen simulierten Bautag (make_scenario_inputs.py) Ende-zu-Ende durch die Pipeline spielen.

  # 1) Vortag (20.11.) als Historie: Demo-Daten per Fixture-Replay – deterministisch, ohne GPU
  SITEVOX_DATA=data/scenario_runs/X SITEVOX_MODE=demo python scripts/seed_demo.py
  # 2) Szenario-Tag mit echten Modellen (vLLM + ASR) in dieselbe Datenbank
  SITEVOX_DATA=data/scenario_runs/X SITEVOX_MODE=gpu python scripts/run_scenario.py data/raw/scenario_SCN-RIEM-0016_en

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
}


def ensure_activities(pid: str, day: str, plan: dict | None) -> None:
    have = {a["id"] for a in store.activities(pid)}
    for aid, extra in EXTRA_ACTIVITIES.items():
        if aid in have:
            continue
        unit, target = "m", 24
        for a in (plan or {}).get("activities", []):
            if a["id"] == aid:
                unit, target = a["unit"], a["daily_target"]
        store.save_activity(pid, {"id": aid, "name": extra["name"], "start": day, "finish": day, "qty": float(target),
                                  "unit": unit, "lv_pos": "", "lv_sum": 0.0, "preds": [], "aliases": extra["aliases"],
                                  "kind": "task", "duration": 1})
        print(f"Vorgang {aid} ({extra['name']}) ergänzt")


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
        f = a.inputs_dir / m["file"]
        ts = f"{day}T{m['time']}:00{TZ}"
        t0 = time.perf_counter()
        umeta = {"source": "mobile", "output_language": out_lang}
        if m["kind"] == "note":
            cap = ingest(pid, "note", text=f.read_text(encoding="utf-8"), captured_at=ts, meta=umeta)
        elif m["kind"] == "audio":
            cap = ingest(pid, "audio", file=f, captured_at=ts, meta=umeta)
        elif m["kind"] == "photo":
            cap = ingest(pid, "photo", file=f, captured_at=ts, meta=umeta, prefer_exif_time=True)
            q = (cap.get("followup") or {}).get("question")
            if m.get("caption"):  # Bildunterschrift des Bauleiters = Antwort auf die Rückfrage
                cap = answer_photo(cap["capture_id"], "note", text=m["caption"], answered_at=ts)
            cap["_question"] = q
        else:
            continue
        dt = time.perf_counter() - t0
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
                                                "asr_score", "text", "meta")},
                      "transcript_text": (c.get("transcript") or {}).get("text"),
                      "language": (c.get("transcript") or {}).get("language"),
                      "vision": (c.get("vision") or {}).get("analysis"), "followup": c.get("followup"),
                      "answer": c.get("answer")} for c in caps.values()],
        "events": list(touched.values()),
        "evidence_capture": {x: (store.evidence(x) or {}).get("capture_id")
                             for e in touched.values() for x in e["evidence"]},
        "letters": [store.get("letters", l["letter_id"]) if isinstance(l, dict) else store.get("letters", l)
                    for l in letters],
        "progress": [p for p in store.progress(pid) if p["date"] == day],
        "staffing": store.staffing(pid, day),
    }
    dst = settings.data_dir() / "run_output.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n{len(touched)} Ereignisse, {len(letters)} Entwürfe → {dst}")


if __name__ == "__main__":
    main()
