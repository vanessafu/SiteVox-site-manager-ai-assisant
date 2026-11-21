"""Render Tagesbericht + Nachtrag JSON (see *.schema.json) into one black-and-white A4 PDF.

Usage: python render_pdf.py tagesbericht.json nachtrag.json out.pdf [font_dir]
Font: D-DIN Pro (Datto, SIL OFL), an open DIN 1451 style typeface, converted to TTF.
Non-German original texts fall back to Liberation Sans (D-DIN lacks e.g. Polish glyphs).
"""
import json, sys, os
from datetime import datetime, date
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_LEFT
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table,
                                TableStyle, PageBreak, KeepTogether, CondPageBreak)
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from xml.sax.saxutils import escape

TB_PATH, NT_PATH, OUT = sys.argv[1:4]
FONT_DIR = sys.argv[4] if len(sys.argv) > 4 else os.path.join(os.path.dirname(__file__), "..", "fonts")

pdfmetrics.registerFont(TTFont("DIN", os.path.join(FONT_DIR, "DDINPro-Regular.ttf")))
pdfmetrics.registerFont(TTFont("DIN-M", os.path.join(FONT_DIR, "DDINPro-Medium.ttf")))
pdfmetrics.registerFont(TTFont("DIN-B", os.path.join(FONT_DIR, "DDINPro-Bold.ttf")))
pdfmetrics.registerFontFamily("DIN", normal="DIN", bold="DIN-B", italic="DIN", boldItalic="DIN-B")
FALLBACK = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
pdfmetrics.registerFont(TTFont("FB", FALLBACK))

BLACK = colors.black
G1 = colors.Color(0.93, 0.93, 0.93)   # light fill
G2 = colors.Color(0.55, 0.55, 0.55)   # rules / secondary text
G3 = colors.Color(0.35, 0.35, 0.35)

S = {
    "title": ParagraphStyle("title", fontName="DIN-B", fontSize=20, leading=24, spaceAfter=2),
    "subtitle": ParagraphStyle("subtitle", fontName="DIN", fontSize=11, leading=14, textColor=G3),
    "h": ParagraphStyle("h", fontName="DIN-B", fontSize=11.5, leading=14, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="DIN", fontSize=10, leading=13.5),
    "bodyj": ParagraphStyle("bodyj", fontName="DIN", fontSize=10.5, leading=14.5, spaceAfter=7),
    "small": ParagraphStyle("small", fontName="DIN", fontSize=8.5, leading=11),
    "smallg": ParagraphStyle("smallg", fontName="DIN", fontSize=8.5, leading=11, textColor=G3),
    "cell": ParagraphStyle("cell", fontName="DIN", fontSize=8.8, leading=11.2),
    "cellb": ParagraphStyle("cellb", fontName="DIN-B", fontSize=8.8, leading=11.2),
    "cellr": ParagraphStyle("cellr", fontName="DIN", fontSize=8.8, leading=11.2, alignment=TA_RIGHT),
    "cellrb": ParagraphStyle("cellrb", fontName="DIN-B", fontSize=8.8, leading=11.2, alignment=TA_RIGHT),
    "th": ParagraphStyle("th", fontName="DIN-M", fontSize=8.3, leading=10.5),
    "thr": ParagraphStyle("thr", fontName="DIN-M", fontSize=8.3, leading=10.5, alignment=TA_RIGHT),
    "label": ParagraphStyle("label", fontName="DIN-M", fontSize=8.3, leading=11, textColor=G3),
    "subject": ParagraphStyle("subject", fontName="DIN-B", fontSize=11, leading=14.5, spaceAfter=10),
}

WD = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MO = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def e(t):
    return escape("" if t is None else str(t))


def P(t, st="cell"):
    return Paragraph(e(t), S[st])


def PX(xml, st="cell"):
    return Paragraph(xml, S[st])


def num(x, d=2):
    if x is None:
        return "–"
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def numsmart(x):
    if x is None:
        return "–"
    return num(x, 0) if float(x).is_integer() else num(x, 2)


def eur(x):
    return num(x) + " €"


def ddate(s):
    d = date.fromisoformat(s[:10])
    return d.strftime("%d.%m.%Y")


def longdate(s):
    d = date.fromisoformat(s[:10])
    return f"{WD[d.weekday()]}, {d.day}. {MO[d.month - 1]} {d.year}"


def dtime(s):
    dt = datetime.fromisoformat(s)
    return dt.strftime("%d.%m.%Y, %H:%M")


def tspan(r):
    if not r:
        return "–"
    a, b = r.get("from"), r.get("to")
    return f"{a or '?'} – {b} Uhr" if b else f"seit {a} Uhr (andauernd)"


def orig(src):
    """Original text, with font fallback for non-German sources."""
    t = e(src.get("original_text"))
    if src.get("original_language", "de") != "de":
        lang = e(src.get("original_language")).upper()
        out = f'<font name="FB" size="8.3">{t}</font> <font color="#595959">[{lang}]</font>'
        if src.get("translation_de"):
            out += f'<br/><font name="DIN-M">Übersetzung (DE):</font> {e(src["translation_de"])}'
        return out
    return t


# ---------------------------------------------------------------- tables
W = A4[0] - 25 * mm - 20 * mm  # content width (DIN 5008 margins left 25, right 20)


def grid(rows, widths, header=True, zebra=False, extra=None):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, G2),
        ("LINEABOVE", (0, 0), (-1, 0), 0.9, BLACK),
    ]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), G1), ("LINEBELOW", (0, 0), (-1, 0), 0.9, BLACK)]
    st += [("LINEBELOW", (0, -1), (-1, -1), 0.9, BLACK)]
    if extra:
        st += extra
    t.setStyle(TableStyle(st))
    return t


def kv(pairs, widths=(32 * mm, None)):
    w2 = widths[1] or (W - widths[0])
    rows = [[P(k, "label"), v if not isinstance(v, str) else P(v)] for k, v in pairs]
    t = Table(rows, colWidths=[widths[0], w2])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
    ]))
    return t


def H(t):
    return [CondPageBreak(30 * mm), Paragraph(e(t), S["h"]),
            Table([[""]], colWidths=[W], rowHeights=[0.1], style=[("LINEABOVE", (0, 0), (-1, -1), 1.2, BLACK)]),
            Spacer(1, 3)]


# ---------------------------------------------------------------- page decoration
class NumberedCanvas(rl_canvas.Canvas):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._pages)
        for st in self._pages:
            self.__dict__.update(st)
            self.setFont("DIN", 8)
            self.setFillColor(G3)
            self.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Seite {self._pageNumber} von {n}")
            super().showPage()
        super().save()


def make_onpage(project_line):
    def onpage(c, doc):
        c.saveState()
        sect = STATE["section"]
        c.setFont("DIN-M", 8)
        c.setFillColor(BLACK)
        c.drawString(25 * mm, A4[1] - 12 * mm, sect)
        c.setFont("DIN", 8)
        c.setFillColor(G3)
        c.drawRightString(A4[0] - 20 * mm, A4[1] - 12 * mm, project_line)
        c.setStrokeColor(BLACK)
        c.setLineWidth(0.6)
        c.line(25 * mm, A4[1] - 14 * mm, A4[0] - 20 * mm, A4[1] - 14 * mm)
        c.line(25 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
        c.drawString(25 * mm, 12 * mm, "KI-gestützter Entwurf. Inhalt vom Bauleiter zu prüfen. Keine Rechtsberatung.")
        c.restoreState()
    return onpage


STATE = {"section": ""}


class Section(Spacer):
    """Zero-height flowable that sets the running header text."""
    def __init__(self, name):
        super().__init__(0, 0)
        self.name = name

    def draw(self):
        STATE["section"] = self.name


# ---------------------------------------------------------------- Tagesbericht
def tagesbericht(d):
    m, story = d["meta"], [Section(f"Bautagesbericht Nr. {d['meta'].get('report_no', '')}")]
    story += [Paragraph(f"Bautagesbericht Nr. {m.get('report_no', '')}", S["title"]),
              Paragraph(longdate(m["date"]), S["subtitle"]), Spacer(1, 8)]

    cw = [30 * mm, W / 2 - 30 * mm, 30 * mm, W / 2 - 30 * mm]
    wh = m.get("working_hours") or {}
    rows = [
        [P("Bauvorhaben", "label"), P(m["project"]["name"]), P("Projekt-Nr.", "label"), P(m["project"].get("project_no"))],
        [P("Baustelle", "label"), P(m["project"].get("address")), P("Vertrag", "label"), P(m["project"].get("contract_no"))],
        [P("Auftraggeber", "label"), P(m["client"]["name"]), P("Auftragnehmer", "label"), P(m["contractor"]["company"])],
        [P("Objektüberwachung", "label"), P(m["client"].get("representative")), P("Bauleitung", "label"), P(m["contractor"]["bauleiter"])],
        [P("Arbeitszeit", "label"), P(f"{wh.get('start', '?')} – {wh.get('end', '?')} Uhr"), P("Polier", "label"), P(m["contractor"].get("polier"))],
    ]
    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.9, BLACK),
                           ("LINEBELOW", (0, 0), (-1, -2), 0.4, G2), ("LINEBEFORE", (2, 0), (2, -1), 0.4, G2),
                           ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
    story.append(t)

    w = d["weather"]
    story += H("1  Witterung")
    rows = [[P(h, "th") for h in ["Wetter", "Temperatur min / max", "Niederschlag", "Arbeitsfähigkeit", "Bemerkung"]],
            [P(w["condition"]), P(f"{numsmart(w['temp_min_c'])} °C / {numsmart(w['temp_max_c'])} °C"),
             P(f"{numsmart(w.get('precipitation_mm'))} mm"), P("gegeben" if w["work_possible"] else "nicht gegeben"),
             P(w.get("impact_note"))]]
    story.append(grid(rows, [24 * mm, 34 * mm, 24 * mm, 26 * mm, W - 108 * mm]))

    story += H("2  Personaleinsatz")
    rows = [[P(h, "th") for h in ["Firma", "Gewerk / Funktion", "Anzahl", "Stunden", "davon Wartezeit"]]]
    for r in d["workforce"]:
        firm = r["company"] + (" (NU)" if r.get("is_subcontractor") else "")
        rows.append([P(firm), P(r["trade"]), P(r["count"], "cellr"), P(numsmart(r.get("hours_total")), "cellr"),
                     P(f"{numsmart(r.get('idle_hours'))} h" if r.get("idle_hours") else "–", "cellr")])
    rows.append([P("Summe", "cellb"), P(""), P(sum(r["count"] for r in d["workforce"]), "cellrb"),
                 P(numsmart(sum(r.get("hours_total", 0) for r in d["workforce"])), "cellrb"),
                 P(f"{numsmart(sum(r.get('idle_hours', 0) for r in d['workforce']))} h", "cellrb")])
    story.append(grid(rows, [52 * mm, 50 * mm, 18 * mm, 22 * mm, W - 142 * mm],
                      extra=[("LINEABOVE", (0, -1), (-1, -1), 0.9, BLACK)]))

    story += H("3  Geräteeinsatz")
    rows = [[P(h, "th") for h in ["Gerät", "Status", "Soll h", "Ist h", "Ausfallzeit", "Ursache"]]]
    for r in d.get("equipment", []):
        rows.append([P(r["name"]), P(r["status"]), P(numsmart(r.get("hours_planned")), "cellr"),
                     P(numsmart(r.get("hours_operated")), "cellr"), P(tspan(r.get("downtime")) if r.get("downtime") else "–"),
                     P(r.get("downtime_cause") or "–")])
    story.append(grid(rows, [50 * mm, 22 * mm, 14 * mm, 14 * mm, 30 * mm, W - 130 * mm]))

    story += H("4  Lieferungen")
    rows = [[P(h, "th") for h in ["Material", "Menge", "Lieferant", "durch", "Soll", "Ist", "Verzug", "Lieferschein"]]]
    for r in d.get("deliveries", []):
        rows.append([P(r["material"]), P(f"{numsmart(r['quantity'])} {r['unit']}", "cellr"), P(r.get("supplier")),
                     P(r["supplied_by"]), P(r.get("planned_time")), P(r.get("actual_time")),
                     P(f"{r.get('delay_minutes', 0)} min", "cellr"), P(r.get("delivery_note_no"))])
    story.append(grid(rows, [40 * mm, 17 * mm, 27 * mm, 11 * mm, 12 * mm, 12 * mm, 15 * mm, W - 134 * mm]))

    story += H("5  Ausgeführte Arbeiten und Leistungsstand")
    rows = [[P(h, "th") for h in ["Vorgang", "Leistung", "Ort", "Soll", "Ist", "Einh.", "Stand"]]]
    for r in d["work_performed"]:
        desc = e(r["description"]) + (' <font color="#595959">(wird verdeckt, Fotodoku)</font>' if r.get("covered_work") else "")
        rows.append([P(r.get("activity_id")), PX(desc), P(r["location"]), P(numsmart(r.get("quantity_planned")), "cellr"),
                     P(numsmart(r.get("quantity_actual")), "cellr"), P(r.get("unit")), P(f"{numsmart(r.get('progress_pct'))} %", "cellr")])
    story.append(grid(rows, [15 * mm, W - 115 * mm, 30 * mm, 14 * mm, 14 * mm, 12 * mm, 15 * mm]))

    if d.get("deviations"):
        story += H("6  Soll-Ist-Abweichungen")
        rows = [[P(h, "th") for h in ["Vorgang", "Kennzahl", "Soll", "Ist", "Abweichung", "Bewertung", "Ereignis"]]]
        for r in d["deviations"]:
            sev = r["severity"]
            rows.append([P(r["activity_id"]), P(r["metric"] + (f" ({r['unit']})" if r.get("unit") else "")),
                         P(numsmart(r["planned"]), "cellr"), P(numsmart(r["actual"]), "cellr"),
                         P(f"{num(r['deviation_pct'], 1)} %", "cellrb"),
                         P(sev.upper() if sev in ("hoch", "kritisch") else sev, "cellb" if sev in ("hoch", "kritisch") else "cell"),
                         P(", ".join(r.get("linked_incident_ids", [])), "small")])
        story.append(grid(rows, [15 * mm, W - 133 * mm, 14 * mm, 14 * mm, 20 * mm, 20 * mm, 50 * mm]))
        risk = [r for r in d["deviations"] if r.get("milestone_at_risk")]
        for r in risk:
            story += [Spacer(1, 3), PX(f'<font name="DIN-B">Meilenstein gefährdet:</font> {e(r["milestone_at_risk"])}', "body")]

    story += H("7  Besondere Vorkommnisse")
    for i, r in enumerate(d["incidents"]):
        imp = r.get("impact", {})
        imp_parts = []
        if imp.get("delay_hours"):
            imp_parts.append(f"Verzug {numsmart(imp['delay_hours'])} h")
        if imp.get("idle_workers"):
            imp_parts.append(f"{imp['idle_workers']} Arbeitskräfte in Wartezeit")
        if imp.get("idle_equipment"):
            imp_parts.append("Stillstand: " + ", ".join(imp["idle_equipment"]))
        if imp.get("schedule_impact"):
            imp_parts.append(imp["schedule_impact"])
        if imp.get("cost_estimate_eur"):
            imp_parts.append(f"Kostenschätzung ca. {eur(imp['cost_estimate_eur'])}")
        head = Table([[PX(f'<font name="DIN-B">{e(r["incident_id"])}</font>   {e(r["type"])}', "cell"),
                       P(tspan(r.get("time")), "cellr")]], colWidths=[W * 0.62, W * 0.38])
        head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), G1), ("LINEABOVE", (0, 0), (-1, 0), 0.9, BLACK),
                                  ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
        pairs = [("Sachverhalt", r["description"]), ("Ursache", r.get("cause"))]
        if r.get("instructing_person"):
            pairs.append(("Anordnung durch", r["instructing_person"]))
        pairs += [("Risikosphäre", PX(f'<font name="DIN-B">{e(r["responsibility_sphere"])}</font>  (Vorschlag des Assistenten)')),
                  ("Begründung", r.get("sphere_reasoning")),
                  ("Auswirkung", "; ".join(imp_parts) or "–"),
                  ("Betroffene Vorgänge", ", ".join(r.get("affected_activities", [])) or "–"),
                  ("Empfohlene Maßnahme", PX(f'<font name="DIN-B">{e(r["suggested_notice"])}</font>')),
                  ("Frist / Hinweis", r.get("notice_deadline_hint") or "–"),
                  ("Status", r.get("notice_status", "offen")),
                  ("Belege", ", ".join(r.get("source_refs", [])))]
        body = kv(pairs, widths=(36 * mm, None))
        box = Table([[head], [body]], colWidths=[W])
        box.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                                 ("LINEBELOW", (0, -1), (-1, -1), 0.9, BLACK)]))
        story += [KeepTogether([box]), Spacer(1, 8)]

    if d.get("photos"):
        story += H("8  Fotodokumentation")
        rows = [[P(h, "th") for h in ["Foto", "Aufnahme", "Ort", "Beschreibung", "Bezug"]]]
        for r in d["photos"]:
            rows.append([P(r["photo_id"]), P(dtime(r["timestamp"])), P(r.get("location")), P(r.get("caption_de")),
                         P(", ".join(r.get("related_ids", [])), "small")])
        story.append(grid(rows, [20 * mm, 27 * mm, 28 * mm, W - 115 * mm, 40 * mm]))

    story += H("9  Quellen und Belege")
    rows = [[P(h, "th") for h in ["ID", "Art", "Zeitpunkt", "Verfasser", "Inhalt"]]]
    for s in d["sources"]:
        rows.append([P(s["source_id"], "small"), P(s["type"], "small"), P(dtime(s["timestamp"]), "small"),
                     P(s.get("author"), "small"), PX(orig(s), "small")])
    story.append(grid(rows, [24 * mm, 20 * mm, 24 * mm, 30 * mm, W - 98 * mm]))

    rv = d["review"]
    story += H("10  Prüfung und Freigabe")
    items = [("Status", rv["status"])]
    if rv.get("unsupported_statements"):
        items.append(("Ohne Beleg", PX("<br/>".join("– " + e(x) for x in rv["unsupported_statements"]))))
    if rv.get("open_questions"):
        items.append(("Rückfragen", PX("<br/>".join("– " + e(x) for x in rv["open_questions"]))))
    story.append(kv(items, widths=(36 * mm, None)))
    story.append(Spacer(1, 18))
    story.append(signatures(["Ort, Datum", "Bauleitung Auftragnehmer", "Auftraggeber / Objektüberwachung"]))
    return story


def signatures(labels):
    n = len(labels)
    gap = 8 * mm
    cw = (W - gap * (n - 1)) / n
    row1, row2, widths = [], [], []
    for i, l in enumerate(labels):
        row1.append("")
        row2.append(P(l, "smallg"))
        widths.append(cw)
        if i < n - 1:
            row1.append(""); row2.append(""); widths.append(gap)
    t = Table([row1, row2], colWidths=widths, rowHeights=[16 * mm, None])
    st = [("TOPPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 0)]
    for i in range(0, len(widths), 2):
        st.append(("LINEBELOW", (i, 0), (i, 0), 0.7, BLACK))
    t.setStyle(TableStyle(st))
    return t


# ---------------------------------------------------------------- Nachtrag
def nachtrag(n):
    m = n["meta"]
    c, cl, ref = m["contractor"], m["client"], n["reference"]
    story = [PageBreak(), Section(f"Nachtragsangebot {m['nachtrag_id']}")]

    sender = f"{c['company']} · {c.get('address', '')}"
    addr = "<br/>".join(e(x) for x in [cl["name"], cl.get("contact"), *cl.get("address", "").split(", ")] if x)
    info = [("Bauvorhaben", m["project"]["name"]), ("Projekt-Nr.", m["project"].get("project_no")),
            ("Vertrag", m["project"].get("contract_no")), ("Nachtrag", f"{m['nachtrag_id']}, Version {m.get('version', 1)}"),
            ("Bearbeiter", c["bauleiter"]), ("Telefon", c.get("phone")), ("E-Mail", c.get("email")),
            ("Datum", ddate(m["date"]))]
    info_t = Table([[P(k, "label"), P(v, "small")] for k, v in info], colWidths=[22 * mm, 52 * mm])
    info_t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    left = [Paragraph(f'<font name="DIN-B" size="13">{e(c["company"])}</font>', S["body"]), Spacer(1, 16),
            Paragraph(f'<u>{e(sender)}</u>', S["smallg"]), Spacer(1, 4), Paragraph(addr, S["bodyj"])]
    head = Table([[left, info_t]], colWidths=[W - 76 * mm, 76 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 14), Paragraph(e(m["subject"]), S["subject"])]

    tr = ref["trigger"]
    mka = ref.get("mehrkostenanzeige") or {}
    cb = n["claim_basis"]
    salutation = "Sehr geehrte Damen und Herren,"
    if cl.get("contact", "").startswith("Herr"):
        salutation = "Sehr geehrter " + cl["contact"].split(",")[0] + ","
    elif cl.get("contact", "").startswith("Frau"):
        salutation = "Sehr geehrte " + cl["contact"].split(",")[0] + ","
    paras = [salutation,
             f"mit {'E-Mail' if 'schriftlich' in tr['type'] else 'Anordnung'} vom {dtime(tr['date'])} Uhr hat "
             f"{tr['by']} folgende Leistung angeordnet: {tr.get('content', '')}",
             f"{n['change_description']['reason']} Diese Leistung ist im vertraglichen Leistungsverzeichnis nicht enthalten.",
             ]
    if mka.get("sent"):
        paras.append(f"Die daraus entstehenden Mehrkosten haben wir Ihnen mit unserer Mehrkostenanzeige {mka.get('reference')} "
                     f"vom {dtime(mka['sent_at'])} Uhr{' vor Beginn der Ausführung' if mka.get('before_execution') else ''} angekündigt.")
    paras.append(f"Für die {cb['category']} bieten wir Ihnen auf Grundlage von {' und '.join(cb['legal_refs'])} "
                 f"die nachfolgenden Positionen an:")
    for p in paras:
        story.append(Paragraph(e(p), S["bodyj"]))

    rows = [[P("Pos.", "th"), P("Leistung", "th"), P("Menge", "thr"), P("Einh.", "th"), P("EP netto", "thr"), P("GP netto", "thr")]]
    for p in n["positions"]:
        txt = f'<font name="DIN-B">{e(p["short_text"])}</font><br/><font size="8" color="#595959">{e(p.get("long_text", ""))}</font>'
        rows.append([P(p["pos"]), PX(txt), P(numsmart(p["quantity"]), "cellr"), P(p["unit"]),
                     P(eur(p["unit_price_eur"]), "cellr"), P(eur(p["total_eur"]), "cellr")])
    t = n["totals"]
    rows += [[P(""), P("Summe netto", "cellb"), "", "", "", P(eur(t["net_eur"]), "cellrb")],
             [P(""), P(f"zzgl. {numsmart(t['vat_pct'])} % Umsatzsteuer"), "", "", "", P(eur(t["vat_eur"]), "cellr")],
             [P(""), P("Nachtragssumme brutto", "cellb"), "", "", "", P(eur(t["gross_eur"]), "cellrb")]]
    k = len(n["positions"]) + 1
    story.append(grid(rows, [15 * mm, W - 92 * mm, 15 * mm, 12 * mm, 24 * mm, 26 * mm],
                      extra=[("LINEABOVE", (0, k), (-1, k), 0.9, BLACK), ("BACKGROUND", (0, -1), (-1, -1), G1),
                             ("LINEBELOW", (0, k), (-1, k + 1), 0, colors.white)]))
    story.append(Spacer(1, 10))

    pb = n["price_basis"]
    sp = pb["surcharges_pct"]
    story.append(Paragraph(e(
        f"Die Einheitspreise sind aus den Ansätzen unserer Urkalkulation zum Hauptauftrag abgeleitet "
        f"(Mittellohn {num(pb.get('wage_rate_eur_h'))} €/h; Zuschläge: Baustellengemeinkosten {numsmart(sp['bgk'])} %, "
        f"Allgemeine Geschäftskosten {numsmart(sp['agk'])} %, Wagnis und Gewinn {numsmart(sp['wg'])} %). "
        f"Die Preisermittlung je Position liegt als Anlage bei."), S["bodyj"]))
    si = n.get("schedule_impact") or {}
    if si:
        story.append(Paragraph(e(f"{si.get('description', '')} Betroffen: {', '.join(si.get('affected_activities', []))}. "
                                 f"{si.get('reservation', '')}"), S["bodyj"]))
    co = n.get("conditions") or {}
    if co.get("execution_note"):
        story.append(Paragraph(e(co["execution_note"]), S["bodyj"]))
    story += [Paragraph("Für Rückfragen stehen wir Ihnen gerne zur Verfügung.", S["bodyj"]), Spacer(1, 4),
              Paragraph("Mit freundlichen Grüßen", S["bodyj"]), Paragraph(e(c["company"]), S["body"]), Spacer(1, 26)]
    sig = Table([[""], [P(f"{c['bauleiter']}, Bauleitung", "smallg")]], colWidths=[65 * mm], rowHeights=[2, None])
    sig.setStyle(TableStyle([("LINEABOVE", (0, 0), (0, 0), 0.7, BLACK), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [sig, Spacer(1, 14)]

    att = n.get("attachments", [])
    if att:
        story.append(KeepTogether([Paragraph("Anlagen", S["cellb"]),
                                   Paragraph("<br/>".join(f"{i + 1}. {e(a)}" for i, a in enumerate(att)), S["small"])]))
    if cl.get("copy_to"):
        story += [Spacer(1, 6), Paragraph("Nachrichtlich: " + e(", ".join(cl["copy_to"])), S["small"])]

    # Anlage: Preisermittlung
    story += [PageBreak(), Section(f"Nachtragsangebot {m['nachtrag_id']} · Anlage"),
              Paragraph("Anlage: Preisermittlung", S["title"]),
              Paragraph(f"{m['nachtrag_id']} · {m['project']['name']} · Methode: {pb['method']}", S["subtitle"]), Spacer(1, 8)]
    fac = sum(sp.values())
    rows = [[P(h, "thr" if i > 1 else "th") for i, h in enumerate(
        ["Pos.", "Einh.", "Lohn h", "Lohn €", "Stoffe €", "Geräte €", "NU €", "EKT €", f"Zuschlag {numsmart(fac)} %", "EP €"])]]
    for p in n["positions"]:
        cc = p.get("calculation", {})
        rows.append([P(p["pos"]), P(p["unit"]), P(num(cc.get("labour_h")), "cellr"), P(num(cc.get("labour_eur")), "cellr"),
                     P(num(cc.get("material_eur")), "cellr"), P(num(cc.get("equipment_eur")), "cellr"),
                     P(num(cc.get("subcontractor_eur")), "cellr"), P(num(cc.get("direct_cost_eur")), "cellr"),
                     P(num(p["unit_price_eur"] - cc.get("direct_cost_eur", 0)), "cellr"), P(num(p["unit_price_eur"]), "cellrb")])
    story.append(grid(rows, [15 * mm, 11 * mm] + [(W - 26 * mm) / 8] * 8))
    story += [Spacer(1, 6), Paragraph(e(
        "EKT = Einzelkosten der Teilleistung je Einheit. EP = EKT × (1 + Zuschläge). " + (pb.get("note") or "")), S["smallg"])]

    # Interner Prüfbogen
    rv = n["review"]
    story += [Spacer(1, 18)] + H("Interner Prüfbogen (nicht Bestandteil des Angebots)")
    rows = [[P("Prüfpunkt", "th"), P("Ergebnis", "th"), P("Anmerkung", "th")]]
    for ch in rv.get("checks", []):
        res = ch["result"]
        rows.append([P(ch["check"]), P(res.upper() if res != "ok" else "ok", "cellb" if res != "ok" else "cell"), P(ch.get("note"))])
    story.append(grid(rows, [58 * mm, 20 * mm, W - 78 * mm]))
    items = [("Status", rv["status"]),
             ("Anspruchsgrundlage", f"{cb['category']}: {', '.join(cb['legal_refs'])}. {cb.get('note', '')}")]
    if rv.get("unsupported_statements"):
        items.append(("Ohne Beleg", PX("<br/>".join("– " + e(x) for x in rv["unsupported_statements"]))))
    if rv.get("open_questions"):
        items.append(("Rückfragen", PX("<br/>".join("– " + e(x) for x in rv["open_questions"]))))
    story += [Spacer(1, 6), kv(items, widths=(36 * mm, None)), Spacer(1, 16),
              signatures(["Ort, Datum", "Freigabe Bauleitung", "Freigabe Kalkulation / Geschäftsleitung"])]
    story += H("Quellen und Belege")
    rows = [[P(h, "th") for h in ["ID", "Art", "Zeitpunkt", "Verfasser", "Inhalt"]]]
    for s in n["sources"]:
        rows.append([P(s["source_id"], "small"), P(s["type"], "small"), P(dtime(s["timestamp"]), "small"),
                     P(s.get("author"), "small"), PX(orig(s), "small")])
    story.append(grid(rows, [31 * mm, 19 * mm, 24 * mm, 28 * mm, W - 102 * mm]))
    return story


def main():
    tb = json.load(open(TB_PATH, encoding="utf-8"))
    nt = json.load(open(NT_PATH, encoding="utf-8"))
    doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=25 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=22 * mm,
                          title=f"Bautagesbericht {tb['meta']['report_id']} und Nachtrag {nt['meta']['nachtrag_id']}",
                          author=tb["meta"]["contractor"]["company"])
    doc.current_section = ""
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f", leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    p = tb["meta"]["project"]
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPageEnd=make_onpage(f"{p['name']} · {p.get('project_no', '')}"))])
    doc.build(tagesbericht(tb) + nachtrag(nt), canvasmaker=NumberedCanvas)


if __name__ == "__main__":
    main()
