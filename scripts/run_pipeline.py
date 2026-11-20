#!/usr/bin/env python3
"""CLI: einzelne Erfassung durch die Pipeline schicken und Ergebnis ausgeben.

  python scripts/run_pipeline.py audio data/raw/rec_0815.m4a --time 2026-11-23T08:15:00+01:00
  python scripts/run_pipeline.py note --text "Kran steht seit 9 Uhr, Seilwinde defekt"
  python scripts/run_pipeline.py email data/raw/mail.eml
  python scripts/run_pipeline.py document data/raw/Protokoll_BB08.pdf --doc-type protokoll
  python scripts/run_pipeline.py draft EVT-2026-11-20-002          # Entwurf für ein Ereignis
  python scripts/run_pipeline.py report --date 2026-11-20          # Bautagesbericht (DOCX)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sitevox import pipeline, store  # noqa: E402
from sitevox.drafting import composer  # noqa: E402
from sitevox.export import docx_export  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["audio", "photo", "note", "email", "document", "draft", "report"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("--project", default="BV-RIEM")
    ap.add_argument("--time", default=None)
    ap.add_argument("--date", default=None)
    ap.add_argument("--text", default=None)
    ap.add_argument("--doc-type", default=None)
    a = ap.parse_args()
    if a.kind == "draft":
        l = composer.create_letter(a.target)
        for s in l["rendered"]:
            print(f"\n## {s.get('title', s['key'])}")
            if "sentences" in s:
                for x in s["sentences"]:
                    print(" -", x["text"], x["evidence"])
            else:
                print(s["text"])
        print("\nNicht belegt:", [i["value"] for i in l["issues"] if i["status"] == "unverified"])
        return
    if a.kind == "report":
        print(docx_export.daily_report_docx(a.project, a.date or datetime.now().date().isoformat()))
        return
    ts = a.time or datetime.now().astimezone().isoformat(timespec="seconds")
    cap = pipeline.ingest(a.project, a.kind, file=Path(a.target) if a.target else None, text=a.text, captured_at=ts,
                          meta={"doc_type": a.doc_type} if a.doc_type else {})
    print(json.dumps({k: cap[k] for k in ("capture_id", "title", "summary", "event_ids")}, ensure_ascii=False, indent=1))
    for eid in cap["event_ids"]:
        e = store.get("events", eid)
        print(f"{eid}: {e['type']} · Sphäre {e['sphere']} ({e['sphere_rule']}) → {e['recommended_document']['kind']}"
              f" · Konfidenz {e['confidence'].get('overall')} · {e['warnings']}")


if __name__ == "__main__":
    main()
