#!/usr/bin/env python3
"""Baut die Demo-Datenbank auf: Stammdaten, Bauzeitenplan, Vortagsleistungen, Wissensbasis,
und spielt dann den 20.11.2026 Erfassung für Erfassung durch die echte Pipeline.

  python scripts/make_demo_data.py && python scripts/seed_demo.py
  SITEVOX_MODE=gpu python scripts/seed_demo.py     # gleiche Eingaben, echte Modelle
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sitevox import rag, settings, store  # noqa: E402
from sitevox.drafting import composer  # noqa: E402
from sitevox.engine import schedule  # noqa: E402
from sitevox.pipeline import answer_photo, ingest, new_evidence  # noqa: E402
from sitevox.understand import documents  # noqa: E402

PID = "BV-RIEM"
DAY = "2026-11-20"
TZ = "+01:00"


def load_knowledge() -> None:
    for f in sorted((settings.ROOT / "data" / "knowledge").glob("*.md")):
        parsed = documents.parse(f)
        store.save_document({"doc_id": f"LEGAL-{f.stem.upper()}", "project_id": "_legal", "title": parsed["pages"][0]
                            ["text"].splitlines()[0].lstrip("# ").strip(), "file": str(f.relative_to(settings.ROOT)),
                             "kind": "rechtsgrundlage", "collection": "legal", "pages": parsed["pages"], "tables": []})
    demo = settings.demo_dir(PID) / "docs"
    kinds = {"Bauvertrag": "vertrag", "LV": "lv", "Planlieferliste": "planlieferliste"}
    files = sorted(demo.glob("*.md")) + sorted(demo.glob("*.pdf"))
    for f in files:
        if f.name.startswith("Protokoll"):
            continue
        if f.suffix == ".md" and f.with_suffix(".pdf").exists():  # Original-PDF hat Vorrang
            continue
        parsed = documents.parse(f)
        kind = next((v for k, v in kinds.items() if f.stem.startswith(k)), "dokument")
        title = {"vertrag": "Bauvertrag RI-2026-014", "lv": "Leistungsverzeichnis Rohbau (LV)",
                 "planlieferliste": "Planlieferliste (Anlage 4)"}.get(kind, f.stem)
        store.save_document({"doc_id": f"DOC-{f.stem}", "project_id": PID, "title": title,  # gleiche ID für MD/PDF
                             "file": str(f.relative_to(settings.ROOT)), "kind": kind, "collection": "project",
                             "pages": parsed["pages"], "tables": parsed["tables"]})
    rag.index(rebuild=True)


def master_evidence() -> None:
    p = settings.project_cfg(PID)
    c = p["client"]
    q = (f"Bauvertrag Nr. {p['contract_no']} vom 14.08.2026; Auftraggeber {c['name']}, {c['address']}; "
         f"bevollmächtigter Vertreter {c['representative']} ({c['representative_role']}); "
         f"Architekturbüro Lechner und Ingenieurbüro Brandl ohne Vollmacht für Nachträge.")
    new_evidence(project_id=PID, source="contract", title=f"Bauvertrag {p['contract_no']} – Stammdaten (S. 1–2)", page=2,
                 quote=q, full_text=q, meta={"master": True, "doc_id": "DOC-Bauvertrag_RI-2026-014"})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-letters", action="store_true", help="keine Entwürfe vorab erzeugen")
    ap.add_argument("--until", default="23:59", help="nur Erfassungen bis HH:MM einspielen (Live-Demo)")
    args = ap.parse_args()

    store.reset()
    for p in settings.baseline()["projects"]:
        store.save_project(p)  # vollständige Stammdaten – in der App editierbar
    acts = schedule.import_plan(settings.demo_dir(PID) / "plan" / "Bauzeitenplan.xlsx")
    for a in acts:
        store.save_activity(PID, a)
    with open(settings.demo_dir(PID) / "history" / "leistung.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            store.save_progress(PID, r["vorgang"], r["datum"], float(r["menge"]), None)
    load_knowledge()
    master_evidence()

    ingest(PID, "document", file=settings.demo_dir(PID) / "docs" / "Protokoll_BB07_2026-11-18.md",
           captured_at=f"2026-11-18T16:00:00{TZ}", title="Protokoll Baubesprechung Nr. 7",
           meta={"doc_type": "protokoll", "doc_id": "DOC-Protokoll_BB07", "doc_title": "Protokoll Baubesprechung Nr. 7"},
           fixture_key="protokoll_bb07")

    manifest = json.loads((settings.demo_dir(PID) / "inputs" / f"{DAY}.json").read_text(encoding="utf-8"))
    for m in manifest:
        if m["time"] > args.until:
            continue
        cap = ingest(PID, m["kind"], file=settings.demo_dir(PID) / "inputs" / DAY / m["file"],
                     captured_at=f"{DAY}T{m['time']}:00{TZ}", title=m.get("title", ""), meta=m.get("meta", {}),
                     fixture_key=m.get("fixture"))
        if m["kind"] == "photo":  # Foto: Rückfrage beantworten (Sprache/Notiz) oder überspringen
            a = m.get("answer") or {"mode": "skip"}
            cap = answer_photo(cap["capture_id"], a["mode"], text=a.get("text"),
                               answered_at=f"{DAY}T{a.get('time', m['time'])}:00{TZ}")
        print(f"  {m['time']} {m['kind']:<6} {cap['capture_id']}  → Ereignisse {cap['event_ids']}")

    if not args.no_letters:
        for e in store.events(PID, DAY):
            if e["recommended_document"]["requires_letter"] and not e.get("letter_id"):
                l = composer.create_letter(e["event_id"])
                open_issues = [i for i in l["issues"] if i["status"] == "unverified"]
                print(f"  Entwurf {l['letter_id']} ({l['kind']}) für {e['event_id']}: "
                      f"{len(open_issues)} nicht belegte Stelle(n)")
    print("\nEreignisse:")
    for e in store.events(PID, DAY):
        print(f"  {e['event_id']} {e['type']:<18} Sphäre {e['sphere']:<7} → {e['recommended_document']['kind']:<22}"
              f" Konfidenz {e['confidence'].get('overall')}  {e['warnings']}")
    print(f"\nDatenbank: {settings.db_path()}")


if __name__ == "__main__":
    main()
