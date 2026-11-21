"""DOCX-Export (python-docx) für Schreiben; PDF über LibreOffice. Bautagesbericht: siehe daily_report.py.

* Interne [E-xx]-Belegverweise werden im Außenschreiben auf Anlagen abgebildet ("vgl. Anlage 2");
  nicht beifügbare Belege (Audio, Engine) entfallen im Außentext, bleiben aber im Audit-Log.
* Fotos werden vor dem Export verpixelt (Gesichter) und mit Zeitstempel + GPS beschriftet.
* Fußzeile: Disclaimer "Entwurf – keine Rechtsberatung …".
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

from .. import DISCLAIMER, settings, store
from . import pdf, privacy

ATTACHABLE = {"photo", "email", "document", "contract", "weather"}


def _doc() -> Document:
    d = Document()
    st = d.styles["Normal"]
    st.font.name, st.font.size = "Arial", Pt(10.5)
    for s in d.sections:
        s.left_margin, s.right_margin, s.top_margin = Cm(2.5), Cm(2), Cm(2)
        fp = s.footer.paragraphs[0]
        fp.text = DISCLAIMER
        fp.runs[0].font.size, fp.runs[0].font.color.rgb = Pt(8), RGBColor(0x66, 0x66, 0x66)
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return d


def _out_dir(project_id: str, day: str) -> Path:
    p = settings.project_files_dir(project_id, day) / "export"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _photo_caption(ev: dict) -> str:
    gps = ev.get("meta", {}).get("gps")
    t = ev.get("captured_at", "")
    when = datetime.fromisoformat(t).strftime("%d.%m.%Y %H:%M") if t else "—"
    g = f" · GPS {gps['lat']:.5f}, {gps['lon']:.5f}" if gps else ""
    return f"{ev.get('title', 'Foto')} · {when}{g}"


def _add_photo(doc: Document, ev: dict, project_id: str, day: str) -> None:
    src = settings.data_dir() / ev["file"] if ev.get("file") else None
    if not src or not src.exists():
        doc.add_paragraph(f"[Foto nicht verfügbar] {_photo_caption(ev)}")
        return
    dst = _out_dir(project_id, day) / f"anon_{src.name}"
    info = privacy.blur_faces(src, dst)
    doc.add_picture(str(dst), width=Cm(12))
    cap = doc.add_paragraph(_photo_caption(ev) + (f" · {info['faces']} Gesicht(er) verpixelt" if info.get("faces")
                                                   else ""))
    cap.runs[0].font.size = Pt(8.5)


def letter_docx(letter: dict) -> dict[str, str]:
    pid = letter["project_id"]
    project = settings.project_cfg(pid)
    company = settings.baseline()["company"]
    ev_docs = {ref: store.evidence(eid) or {} for ref, eid in letter["evidence_map"].items()}
    anl: dict[str, int] = {}
    for ref, d in ev_docs.items():
        if d.get("source") in ATTACHABLE and not d.get("meta", {}).get("master"):
            anl[ref] = len(anl) + 1

    doc = _doc()
    p = doc.add_paragraph(f"{company['name']} · {company['address']}")
    p.runs[0].font.size = Pt(8)
    f = letter["fields"]
    doc.add_paragraph(f"{project['client']['name']}\nz. Hd. {project['client']['representative']}\n"
                      f"{project['client']['address']}")
    dp = doc.add_paragraph(f"München, {date.today():%d.%m.%Y}")
    dp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    doc.add_paragraph(f"Zustellung: {f['delivery_method']['value']}").runs[0].font.size = Pt(8.5)
    for sec in letter["rendered"]:
        if sec["key"] == "betreff":
            r = doc.add_paragraph().add_run(sec["text"])
            r.bold = True
        elif "sentences" in sec:
            doc.add_paragraph().add_run(sec["title"]).bold = True
            parts = []
            for s in sec["sentences"]:
                text = re.sub(r"\s*\[E-\d+\]", "", s["text"]).strip()
                refs = sorted({anl[e] for e in s["evidence"] if e in anl})
                parts.append(text + (f" (vgl. Anlage {', '.join(map(str, refs))})" if refs else ""))
            doc.add_paragraph(" ".join(parts))
        elif sec["key"] == "bezug":
            doc.add_paragraph(f"Bezug: {sec['text']}")
        else:
            doc.add_paragraph(sec["text"])
    if anl:
        doc.add_page_break()
        doc.add_paragraph().add_run("Anlagen").bold = True
        for ref, n in anl.items():
            d = ev_docs[ref]
            doc.add_paragraph(f"Anlage {n}: {d.get('title')}"
                              + (f", S. {d['page']}" if d.get("page") else ""))
            if d["source"] == "photo":
                _add_photo(doc, d, pid, (d.get("captured_at") or date.today().isoformat())[:10])
            elif d.get("quote"):
                q = doc.add_paragraph(d["quote"][:1500])
                q.runs[0].font.size, q.runs[0].italic = Pt(9), True
    day = (store.get("events", letter["event_id"]) or {}).get("date", date.today().isoformat())
    out = _out_dir(pid, day) / f"{letter['letter_id']}_{letter['kind']}.docx"
    doc.save(out)
    pdf_path = pdf.to_pdf(out)
    return {"docx": str(out), **({"pdf": str(pdf_path)} if pdf_path else {})}


def daily_report_docx(project_id: str, day: str) -> dict[str, str]:
    """Bautagesbericht (PDF/DOCX/JSON) – delegiert an daily_report, damit es nur ein Layout gibt."""
    from . import daily_report

    return daily_report.export_files(project_id, day)
