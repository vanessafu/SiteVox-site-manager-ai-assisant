"""DOCX-Export (python-docx) für Schreiben und Bautagesbericht; PDF über LibreOffice.

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
from ..engine import deviation, timeline
from ..schemas import DOC_KIND_LABELS, EVENT_TYPE_LABELS
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
    """Bautagesbericht-Entwurf aus Fotos, Notizen, Terminen und Ereignissen."""
    project = settings.project_cfg(project_id)
    a = deviation.analyze(project_id, date.fromisoformat(day))
    wx = store.weather(project_id, day) or {}
    doc = _doc()
    doc.add_heading(f"Bautagesbericht {date.fromisoformat(day):%A, %d.%m.%Y}".replace(
        "Monday", "Montag").replace("Tuesday", "Dienstag").replace("Wednesday", "Mittwoch").replace(
        "Thursday", "Donnerstag").replace("Friday", "Freitag"), level=1)
    doc.add_paragraph(f"{project['title']} · Vertrag Nr. {project['contract_no']} · Bauleitung "
                      f"{settings.baseline()['company']['signer']}")
    s = wx.get("summary", {})
    if s.get("available"):
        doc.add_paragraph(f"Wetter (DWD via Bright Sky): {s['temp_min']:.0f}–{s['temp_max']:.0f} °C, "
                          f"Niederschlag {s['precip_sum']:.1f} mm, Böen {s['gust_max']:.0f} km/h · Bewertung: "
                          f"{'; '.join(wx['assessment']['reasons'])}")
    doc.add_heading("Personal", level=2)
    for r in store.staffing(project_id, day):
        doc.add_paragraph(f"{r['crew']}: {r['present']} anwesend (Soll {r['planned']})", style="List Bullet")
    doc.add_heading("Leistungen (Soll-Ist)", level=2)
    t = doc.add_table(rows=1, cols=5)
    t.style = "Light Grid Accent 1"
    for c, h in zip(t.rows[0].cells, ["Vorgang", "Tagessoll", "Ist", "Erfüllung", "Prognose Ende"]):
        c.text = h
    for r in a["activities"]:
        if r["today"]["soll"] or r["today"]["ist"]:
            row = t.add_row().cells
            ratio = r["today"]["ratio"]
            row[0].text = r["name"]
            row[1].text = f"{r['today']['soll']:g} {r['unit']}".replace(".", ",")
            row[2].text = f"{r['today']['ist']:g} {r['unit']}".replace(".", ",")
            row[3].text = f"{ratio:.0%}" if ratio is not None else "—"
            row[4].text = f"{date.fromisoformat(r['forecast_finish']):%d.%m.} ({r['delay_days']:+d} AT)"
    doc.add_heading("Geräte / Kolonnen", level=2)
    tl = timeline.day_timeline(project_id, day, {r["id"] for r in a["activities"] if r["today"]["soll"]})
    labels = {"work": "Arbeit", "restricted": "eingeschränkt", "idle": "Stillstand",
              "planned_not_started": "geplant, nicht begonnen"}
    for row in tl["rows"]:
        doc.add_paragraph(f"{row['name']}: " + ", ".join(f"{s['start']}–{s['end']} {labels[s['status']]}"
                                                        for s in row["segments"]), style="List Bullet")
    doc.add_heading("Besondere Vorkommnisse", level=2)
    for e in store.events(project_id, day):
        if e["status"] == "dismissed":
            continue
        doc.add_paragraph(f"{e['start'][11:16]} {EVENT_TYPE_LABELS[e['type']]} – {e['description']} "
                          f"[Sphäre {e['sphere']} (Vorschlag) · {DOC_KIND_LABELS[e['recommended_document']['kind']]}]",
                          style="List Bullet")
    for ch in a["impact"]:
        doc.add_paragraph(f"Auswirkung: {ch['text']}", style="List Bullet")
    doc.add_heading("Erfassungen", level=2)
    for c in store.captures(project_id, day):
        doc.add_paragraph(f"{c['captured_at'][11:16]} {c['title']}: {(c.get('summary') or '')[:200]}",
                          style="List Bullet")
    photos = [store.evidence(c["evidence_ids"][0]) for c in store.captures(project_id, day)
              if c["kind"] == "photo" and c["evidence_ids"]]
    if photos:
        doc.add_page_break()
        doc.add_heading("Fotodokumentation", level=2)
        for ev in photos:
            _add_photo(doc, ev, project_id, day)
    out = _out_dir(project_id, day) / f"Bautagesbericht_{project_id}_{day}.docx"
    doc.save(out)
    pdf_path = pdf.to_pdf(out)
    return {"docx": str(out), **({"pdf": str(pdf_path)} if pdf_path else {})}
