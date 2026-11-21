"""Bautagesbericht als DOCX – gleiches Layout und gleiche Abschnitte wie das PDF (report_pdf.py).

Eingabe ist das Dict aus ``daily_report.build``; Zahlen-/Datumsformate kommen aus report_pdf, damit
PDF und DOCX identisch beschriftet sind. Schrift: Arial (D-DIN ist in Word i. d. R. nicht installiert).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Optional, Union

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from .. import DISCLAIMER
from . import report_pdf
from .report_pdf import dtime, fmt_deviation, longdate, num, numsmart, pct, tspan

FONT = "Arial"
GREY = RGBColor(0x59, 0x59, 0x59)
G1 = "EDEDED"      # Tabellenkopf / Ereigniskopf
RULE = "8C8C8C"    # dünne Zwischenlinien
W_MM = 165         # Satzspiegel: A4 210 − 25 links − 20 rechts

# Zelleninhalt: Text oder Liste von (Text, Stil) – Stil: b (fett), g (grau), s (Größe pt); "\n" = Zeilenumbruch
Rich = Union[str, None, list]


# ------------------------------------------------------------------------------------------- low-level helpers
def _border_el(tag: str, sz: int, color: str) -> Any:
    el = OxmlElement(f"w:{tag}")
    el.set(qn("w:val"), "single" if sz else "nil")
    el.set(qn("w:sz"), str(sz))
    el.set(qn("w:space"), "0")
    el.set(qn("w:color"), color)
    return el


def _table_borders(table, **edges: tuple[int, str]) -> None:
    """edges: top/bottom/left/right/insideH/insideV = (Stärke in 1/8 pt, Farbe); fehlende = keine Linie."""
    tblPr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for tag in ("top", "left", "bottom", "right", "insideH", "insideV"):
        sz, color = edges.get(tag, (0, "auto"))
        b.append(_border_el(tag, sz, color))
    tblPr.append(b)


def _cell_border(cell, **edges: tuple[int, str]) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    b = tcPr.find(qn("w:tcBorders"))
    if b is None:
        b = OxmlElement("w:tcBorders")
        tcPr.append(b)
    for tag, (sz, color) in edges.items():
        b.append(_border_el(tag, sz, color))


def _shade(cell, fill: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _fixed(table, widths_mm: list[float]) -> None:
    table.autofit = False
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    table._tbl.tblPr.append(layout)
    for row in table.rows:
        for c, w in zip(row.cells, widths_mm):
            c.width = Mm(w)


def _para_border(p, tag: str, sz: int, color: str = "000000") -> None:
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    el = _border_el(tag, sz, color)
    el.set(qn("w:space"), "1")
    bdr.append(el)
    pPr.append(bdr)


def _tight(p, before: float = 0, after: float = 0) -> None:
    pf = p.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(before), Pt(after), 1.0


def _write(p, content: Rich, size: float = 8.8, bold: bool = False, grey: bool = False,
           align: Optional[str] = None) -> None:
    if align == "r":
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    segs = [(("–" if content in (None, "") else str(content)), {})] if not isinstance(content, list) else content
    for text, st in segs:
        for i, line in enumerate(str(text).split("\n")):
            if i:
                p.add_run().add_break()
            r = p.add_run(line)
            r.font.name, r.font.size = FONT, Pt(st.get("s", size))
            r.bold = st.get("b", bold)
            if st.get("g", grey):
                r.font.color.rgb = GREY


def _cell(cell, content: Rich, **kw) -> None:
    p = cell.paragraphs[0]
    _tight(p)
    _write(p, content, **kw)


def _no_split(row) -> None:
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:cantSplit")
    trPr.append(el)


def _repeat_header(row) -> None:
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    trPr.append(el)


# ------------------------------------------------------------------------------------------- building blocks
def grid(doc, header: list[str], rows: list[list[Rich]], widths: list[float], align: str = "",
         strong: Optional[list[list[bool]]] = None, total_row: bool = False) -> None:
    """Tabelle wie im PDF: grauer Kopf, schwarze Kopf-/Fußlinie, graue Zwischenlinien. align: je Spalte l/r."""
    t = doc.add_table(rows=1 + len(rows), cols=len(header))
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    _fixed(t, widths)
    _table_borders(t, top=(7, "000000"), bottom=(7, "000000"), insideH=(3, RULE))
    al = (align or "l" * len(header)).ljust(len(header), "l")
    for j, h in enumerate(header):
        c = t.rows[0].cells[j]
        _shade(c, G1)
        _cell_border(c, bottom=(7, "000000"))
        _cell(c, h, size=8.3, bold=True, align=al[j])
    _repeat_header(t.rows[0])
    for i, r in enumerate(rows, start=1):
        _no_split(t.rows[i])
        for j, v in enumerate(r):
            _cell(t.rows[i].cells[j], v, align=al[j], bold=bool(strong and strong[i - 1][j]))
    if total_row:
        for c in t.rows[-1].cells:
            _cell_border(c, top=(7, "000000"))


def kv(doc, pairs: list[tuple[str, Rich]], label_w: float = 36) -> None:
    t = doc.add_table(rows=len(pairs), cols=2)
    _fixed(t, [label_w, W_MM - label_w])
    _table_borders(t)
    for (k, v), row in zip(pairs, t.rows):
        _cell(row.cells[0], k, size=8.3, grey=True)
        _cell(row.cells[1], v)


def note(doc, text: str) -> None:
    p = doc.add_paragraph()
    _tight(p, 2, 2)
    _write(p, text, size=8.5, grey=True)


class Heading:
    def __init__(self, doc) -> None:
        self.doc, self.n = doc, 0

    def __call__(self, title: str) -> None:
        self.n += 1
        p = self.doc.add_paragraph()
        _tight(p, 10, 3)
        p.paragraph_format.keep_with_next = True
        _write(p, f"{self.n}  {title}", size=11.5, bold=True)
        _para_border(p, "bottom", 10)


def _field(p, instr: str) -> None:
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instr)
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "16")
    rpr.append(sz)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    p._p.append(fld)


def _page_frame(doc, left: str, right: str) -> None:
    s = doc.sections[0]
    s.page_width, s.page_height = Mm(210), Mm(297)
    s.left_margin, s.right_margin, s.top_margin, s.bottom_margin = Mm(25), Mm(20), Mm(22), Mm(22)
    s.header_distance, s.footer_distance = Mm(10), Mm(10)
    hp = s.header.paragraphs[0]
    hp.paragraph_format.tab_stops.add_tab_stop(Mm(W_MM), WD_TAB_ALIGNMENT.RIGHT)
    _write(hp, [(left, {"b": True, "s": 8}), ("\t" + right, {"g": True, "s": 8})])
    _para_border(hp, "bottom", 5)
    fp = s.footer.paragraphs[0]
    fp.paragraph_format.tab_stops.add_tab_stop(Mm(W_MM), WD_TAB_ALIGNMENT.RIGHT)
    _para_border(fp, "top", 5)
    _write(fp, [(DISCLAIMER.strip() + "\tSeite ", {"g": True, "s": 8})])
    _field(fp, "PAGE")
    _write(fp, [(" von ", {"g": True, "s": 8})])
    _field(fp, "NUMPAGES")


# ------------------------------------------------------------------------------------------- report
def render(d: dict, out: Path, photo_files: Optional[dict[str, Path]] = None) -> Path:
    photo_files = photo_files or {}
    m = d["meta"]
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = FONT, Pt(10)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    p_ = m["project"]
    _page_frame(doc, f"Bautagesbericht Nr. {m.get('report_no') or ''}", f"{p_['name']} · {p_.get('project_no') or ''}")
    H = Heading(doc)

    title = doc.paragraphs[0] if doc.paragraphs else doc.add_paragraph()
    _tight(title, 0, 2)
    _write(title, f"Bautagesbericht Nr. {m.get('report_no') or ''}", size=20, bold=True)
    sub = doc.add_paragraph()
    _tight(sub, 0, 8)
    _write(sub, longdate(m["date"]), size=11, grey=True)

    # Kopfdaten
    wh = m.get("working_hours") or {}
    head = [("Bauvorhaben", p_["name"], "Projekt-Nr.", p_.get("project_no")),
            ("Baustelle", p_.get("address"), "Vertrag", p_.get("contract_no")),
            ("Auftraggeber", m["client"]["name"], "Auftragnehmer", m["contractor"]["company"]),
            ("Vertreter AG", m["client"].get("representative"), "Bauleitung", m["contractor"]["bauleiter"]),
            ("Arbeitszeit", f"{wh.get('start', '?')} – {wh.get('end', '?')} Uhr", "Verfasser", m.get("author"))]
    t = doc.add_table(rows=len(head), cols=4)
    _fixed(t, [30, W_MM / 2 - 30, 30, W_MM / 2 - 30])
    _table_borders(t, top=(7, "000000"), bottom=(7, "000000"), left=(7, "000000"), right=(7, "000000"),
                   insideH=(3, RULE))
    for row, (a, b, c, e_) in zip(t.rows, head):
        _cell(row.cells[0], a, size=8.3, grey=True)
        _cell(row.cells[1], b, size=9.5)
        _cell(row.cells[2], c, size=8.3, grey=True)
        _cell(row.cells[3], e_, size=9.5)
        _cell_border(row.cells[2], left=(3, RULE))

    # 1 Witterung
    H("Witterung")
    w = d.get("weather")
    if w:
        grid(doc, ["Wetter", "Temperatur min / max", "Niederschlag", "Wind", "Arbeitsfähigkeit", "Bewertung"],
             [[w["condition"], f"{numsmart(w['temp_min_c'])} °C / {numsmart(w['temp_max_c'])} °C",
               f"{numsmart(w.get('precipitation_mm'))} mm", w.get("wind"),
               "gegeben" if w["work_possible"] else "nicht gegeben", w.get("impact_note")]],
             [20, 30, 21, 24, 24, W_MM - 119])
    else:
        note(doc, "Keine Wetterdaten verfügbar (Koordinaten der Baustelle fehlen oder Wetterdienst nicht erreichbar).")

    # 2 Personal
    H("Personaleinsatz")
    wf = d["workforce"]
    refs = report_pdf.SHOW_EVIDENCE_REFS  # gemeinsamer Schalter für PDF und Word
    rows, strong = [], []
    for r in wf:
        ist = "–" if r["count"] is None else str(r["count"]) + (" *" if r.get("derived") else "")
        rows.append([[(r["crew"], {}), ("\n" + r["company"], {"g": True, "s": 7.5})], r["trade"], str(r["planned"]), ist,
                     numsmart(r.get("hours_total")), f"{numsmart(r['idle_hours'])} h" if r.get("idle_hours") else "–"]
                    + ([[(", ".join(r.get("source_refs", [])) or "–", {"s": 8})]] if refs else []))
        strong.append([False, False, False, r["count"] is not None and r["count"] < r["planned"], False, False]
                      + ([False] if refs else []))
    known = [r for r in wf if r["count"] is not None]
    idle = sum(r["idle_hours"] or 0 for r in wf)
    rows.append(["Summe", "", str(sum(r["planned"] for r in wf)), str(sum(r["count"] for r in known)) if known else "–",
                 numsmart(sum(r["hours_total"] or 0 for r in wf)), f"{numsmart(idle)} h" if idle else "–"]
                + ([""] if refs else []))
    strong.append([True] * (7 if refs else 6))
    if refs:
        grid(doc, ["Firma / Kolonne", "Gewerk", "Soll", "Ist", "Stunden", "davon Stillstand", "Belege"], rows,
             [44, 24, 13, 13, 17, 22, W_MM - 133], align="llrrrrl", strong=strong, total_row=True)
    else:
        grid(doc, ["Firma / Kolonne", "Gewerk", "Soll", "Ist", "Stunden", "davon Stillstand"], rows,
             [W_MM - 89, 24, 13, 13, 17, 22], align="llrrrr", strong=strong, total_row=True)
    if any(r.get("derived") for r in wf):
        note(doc, "* nicht einzeln erfasst – aus der gemeldeten Gesamtzahl abgeleitet.")

    # 3 Geräte
    H("Geräteeinsatz")
    if d["equipment"]:
        grid(doc, ["Gerät", "Status", "Soll h", "Ist h", "Ausfallzeit", "Ursache / Bemerkung"],
             [[r["name"] + (" *" if r.get("unplanned") else ""), r["status"], numsmart(r.get("hours_planned")),
               numsmart(r.get("hours_operated")), "\n".join(tspan(x) for x in r.get("downtime", [])) or "–",
               "; ".join(x for x in (r.get("downtime_cause"), r.get("remarks")) if x) or None] for r in d["equipment"]],
             [30, 24, 13, 13, 27, W_MM - 107], align="llrrll",
             strong=[[False, r["status"] != "im Einsatz", False, False, False, False] for r in d["equipment"]])
        if any(r.get("unplanned") for r in d["equipment"]):
            note(doc, "* nicht im Einsatzplan – nur aus Meldungen bekannt.")
    else:
        note(doc, "Kein Großgerät im Tagesverlauf erfasst.")

    # 4 Lieferungen
    H("Lieferungen")
    if d.get("deliveries"):
        def _st(r):
            st = r.get("status") or "geliefert"
            return st + (f" (angek. {date.fromisoformat(r['announced_on']):%d.%m.})" if r.get("announced_on") else "")
        grid(doc, ["Material", "Menge", "Lieferant", "durch", "Soll", "Ist", "Verzug", "Status", "bisher ges."],
             [[r["material"], f"{numsmart(r['quantity'])} {r['unit']}" if r.get("quantity") is not None else "–",
               r.get("supplier"), r.get("supplied_by"), r.get("planned_time"), r.get("actual_time"),
               f"{r['delay_minutes']} min" if r.get("delay_minutes") is not None else "–", _st(r),
               f"{numsmart(r['total_to_date'])} {r['unit']}" if r.get("total_to_date") is not None else "–"]
              for r in d["deliveries"]], [34, 16, 24, 10, 11, 11, 13, W_MM - 137, 18], align="lrllllrlr")
    else:
        note(doc, "Keine Lieferungen erfasst.")

    # 4b Tagesbuch
    if d.get("site_log"):
        H("Prüfungen, Besuche und weitere Feststellungen")
        grid(doc, ["Zeit", "Art", "Feststellung", "Details"],
             [[r.get("time"), r["label"], r["text"], r.get("detail")] for r in d["site_log"]],
             [13, 26, W_MM - 89, 50], align="llll")

    # 5 Leistungen
    H("Ausgeführte Arbeiten und Leistungsstand")
    rows, strong = [], []
    for r in d["work_performed"]:
        fc = date.fromisoformat(r["forecast_finish"]).strftime("%d.%m.") if r.get("forecast_finish") else "–"
        if r.get("delay_days"):
            fc += f" ({r['delay_days']:+d} AT)"
        name: Rich = [(r["description"], {})] + ([(" (krit. Weg)", {"g": True})] if r.get("critical") else [])
        rows.append([r["activity_id"], name, numsmart(r["quantity_planned"]), numsmart(r["quantity_actual"]), r["unit"],
                     pct(r.get("ratio_pct")), pct(r.get("progress_pct")), fc])
        low = r.get("ratio_pct") is not None and r["ratio_pct"] < 100
        strong.append([False, False, False, False, False, low, False, bool(r.get("delay_days"))])
    grid(doc, ["Vorgang", "Leistung", "Tagessoll", "Ist", "Einh.", "Erfüllung", "Gesamt", "Prognose Ende"], rows,
         [14, W_MM - 122, 17, 14, 11, 17, 16, 33], align="llrrlrrl", strong=strong)

    # 6 Soll-Ist-Abweichungen
    if d.get("deviations") or d.get("milestones_at_risk") or d.get("impact_chains"):
        H("Soll-Ist-Abweichungen")
        if d.get("deviations"):
            rows, strong = [], []
            for r in d["deviations"]:
                soll, ist, dev = fmt_deviation(r)
                rows.append([r["activity_id"], r["metric"], soll, ist, dev,
                             [("\n".join(r.get("linked_incident_ids", [])) or "–", {"s": 8})]])
                strong.append([False, False, False, False, True, False])
            grid(doc, ["Vorgang", "Kennzahl", "Soll", "Ist", "Abweichung", "Ereignis"], rows,
                 [13, W_MM - 100, 17, 17, 19, 34], align="llrrrl", strong=strong)
        for label, items in (("Meilenstein gefährdet: ", d.get("milestones_at_risk", [])),
                             ("Auswirkungskette: ", d.get("impact_chains", []))):
            for txt in items:
                p = doc.add_paragraph()
                _tight(p, 3, 0)
                _write(p, [(label, {"b": True}), (txt, {})], size=10)

    # 7 Besondere Vorkommnisse
    H("Besondere Vorkommnisse")
    if not d["incidents"]:
        note(doc, "Keine besonderen Vorkommnisse.")
    for r in d["incidents"]:
        pairs: list[tuple[str, Rich]] = [
            ("Sachverhalt", r.get("description")), ("Ursache", r.get("cause")),
            ("Risikosphäre", [(r.get("responsibility_sphere") or "–", {"b": True}), (f"  ({r.get('sphere_note')})", {})]),
            ("Begründung", r.get("sphere_reasoning")),
            ("Auswirkung", "; ".join(r.get("impact", [])) or None),
            ("Betroffene Vorgänge", ", ".join(r.get("affected_activities", [])) or None),
            ("Empfohlene Maßnahme", [(r.get("suggested_notice") or "–", {"b": True})]),
            ("Frist / Hinweis", r.get("notice_deadline_hint"))]
        if r.get("warnings"):
            pairs.append(("Warnung", [("\n".join(r["warnings"]), {"b": True})]))
        pairs += [("Status", r.get("notice_status")),
                  ("Konfidenz", num(r["confidence"]) if r.get("confidence") is not None else None)]
        if refs:
            pairs.append(("Belege", ", ".join(r.get("source_refs", [])) or None))
        t = doc.add_table(rows=1 + len(pairs), cols=2)
        _fixed(t, [36, W_MM - 36])
        _table_borders(t, top=(7, "000000"), bottom=(7, "000000"))
        hc = t.rows[0].cells[0].merge(t.rows[0].cells[1])
        _shade(hc, G1)
        hp = hc.paragraphs[0]
        _tight(hp, 1, 1)
        hp.paragraph_format.tab_stops.add_tab_stop(Mm(W_MM - 4), WD_TAB_ALIGNMENT.RIGHT)
        _write(hp, [(r["incident_id"], {"b": True}), (f"   {r['type']}\t{tspan(r.get('time'))}", {})])
        for (k, v), row in zip(pairs, t.rows[1:]):
            _cell(row.cells[0], k, size=8.3, grey=True)
            _cell(row.cells[1], v)
        for row in t.rows[:-1]:  # Ereignis möglichst nicht über einen Seitenumbruch reißen
            _no_split(row)
            for c in row.cells:
                for p in c.paragraphs:
                    p.paragraph_format.keep_with_next = True
        doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # 8 Fotos
    if d.get("photos"):
        H("Fotodokumentation")
        t = doc.add_table(rows=1 + len(d["photos"]), cols=5)
        widths = [17, 39, 27, W_MM - 121, 38]
        _fixed(t, widths)
        _table_borders(t, top=(7, "000000"), bottom=(7, "000000"), insideH=(3, RULE))
        for j, h in enumerate(["Foto", "Bild", "Aufnahme / Ort", "Beschreibung", "Bezug"]):
            c = t.rows[0].cells[j]
            _shade(c, G1)
            _cell_border(c, bottom=(7, "000000"))
            _cell(c, h, size=8.3, bold=True)
        for r, row in zip(d["photos"], t.rows[1:]):
            _no_split(row)
            _cell(row.cells[0], r["photo_id"])
            f = photo_files.get(r["photo_id"])
            if f and f.exists():
                p = row.cells[1].paragraphs[0]
                _tight(p)
                p.add_run().add_picture(str(f), width=Mm(36))
            else:
                _cell(row.cells[1], "nicht verfügbar", grey=True)
            _cell(row.cells[2], f"{dtime(r['timestamp'])}\n{r.get('location') or '–'}", size=8.5)
            _cell(row.cells[3], r.get("caption_de"))
            _cell(row.cells[4], ", ".join(r.get("related_ids", [])) or "–", size=8.5)
        note(doc, "Gesichter vor dem Export automatisch verpixelt (DSGVO).")

    # Quellenanhang nur mit SHOW_EVIDENCE_REFS – sonst Belege nur im Dashboard
    if refs:
        H("Quellen und Belege")
        rows = []
        for s in d["sources"]:
            text: Rich = s.get("original_text")
            lang = s.get("original_language") or "de"
            if lang != "de":
                text = [(s.get("original_text") or "–", {}), (f" [{lang.upper()}]", {"g": True})]
                if s.get("translation_de"):
                    text += [("\nÜbersetzung (DE): ", {"b": True}), (s["translation_de"], {})]
            rows.append([s["source_id"], s["type"], dtime(s.get("timestamp")), s.get("author"), text])
        grid(doc, ["ID", "Art", "Zeitpunkt", "Verfasser", "Inhalt"], [[[(c, {"s": 8.5})] if isinstance(c, str) else c
                                                                       for c in r] for r in rows],
             [25, 21, 24, 30, W_MM - 100])

    # 9 Prüfung
    H("Prüfung und Freigabe")
    rv = d["review"]
    items: list[tuple[str, Rich]] = [("Status", rv["status"])]
    for label, key in (("Ohne Beleg", "unsupported_statements"), ("Unsicher", "uncertain"), ("Rückfragen", "open_questions")):
        if rv.get(key):
            items.append((label, "\n".join("– " + x for x in rv[key])))
    kv(doc, items)
    doc.add_paragraph().paragraph_format.space_after = Pt(18)
    sig = doc.add_table(rows=2, cols=5)
    gap = 8
    cw = (W_MM - 2 * gap) / 3
    _fixed(sig, [cw, gap, cw, gap, cw])
    _table_borders(sig)
    sig.rows[0].height = Mm(16)
    for j, label in zip((0, 2, 4), ("Ort, Datum", "Bauleitung Auftragnehmer", "Auftraggeber / Vertreter AG")):
        _cell_border(sig.rows[0].cells[j], bottom=(6, "000000"))
        _cell(sig.rows[1].cells[j], label, size=8.5, grey=True)

    doc.save(str(out))
    return out
