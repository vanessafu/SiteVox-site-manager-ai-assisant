"""Bautagesbericht als schwarz-weißes A4-PDF (reportlab, D-DIN Pro, Satzspiegel nach DIN 5008).

Eingabe ist das Dict aus ``daily_report.build``. Kein LibreOffice nötig.
Schrift: D-DIN Pro (Datto, SIL OFL) in ``fonts/``; Zeichen ohne Glyphe in D-DIN (z. B. „→“, polnische
Sonderzeichen) werden automatisch in einer Systemschrift (Arial / Liberation / DejaVu) gesetzt.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, Image, KeepTogether, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

from .. import DISCLAIMER

FONT_DIR = Path(__file__).parent / "fonts"
FALLBACKS = [r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial Unicode.ttf",
             "/System/Library/Fonts/Supplemental/Arial.ttf"]

_FONTS: dict[str, Any] = {}


def _register_fonts() -> None:
    if _FONTS:
        return
    din = TTFont("DIN", str(FONT_DIR / "DDINPro-Regular.ttf"))
    pdfmetrics.registerFont(din)
    pdfmetrics.registerFont(TTFont("DIN-M", str(FONT_DIR / "DDINPro-Medium.ttf")))
    pdfmetrics.registerFont(TTFont("DIN-B", str(FONT_DIR / "DDINPro-Bold.ttf")))
    pdfmetrics.registerFontFamily("DIN", normal="DIN", bold="DIN-B", italic="DIN", boldItalic="DIN-B")
    _FONTS["cmap"] = set(din.face.charToGlyph)
    _FONTS["fb"] = None
    for p in FALLBACKS:
        if Path(p).exists():
            fb = TTFont("FB", p)
            pdfmetrics.registerFont(fb)
            _FONTS["fb"], _FONTS["fb_cmap"] = "FB", set(fb.face.charToGlyph)
            break


BLACK = colors.black
G1 = colors.Color(0.93, 0.93, 0.93)  # helle Fläche
G2 = colors.Color(0.55, 0.55, 0.55)  # Linien / Sekundärtext
G3 = colors.Color(0.35, 0.35, 0.35)

S = {
    "title": ParagraphStyle("title", fontName="DIN-B", fontSize=20, leading=24, spaceAfter=2),
    "subtitle": ParagraphStyle("subtitle", fontName="DIN", fontSize=11, leading=14, textColor=G3),
    "h": ParagraphStyle("h", fontName="DIN-B", fontSize=11.5, leading=14, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="DIN", fontSize=10, leading=13.5),
    "small": ParagraphStyle("small", fontName="DIN", fontSize=8.5, leading=11),
    "smallg": ParagraphStyle("smallg", fontName="DIN", fontSize=8.5, leading=11, textColor=G3),
    "cell": ParagraphStyle("cell", fontName="DIN", fontSize=8.8, leading=11.2),
    "cellb": ParagraphStyle("cellb", fontName="DIN-B", fontSize=8.8, leading=11.2),
    "cellr": ParagraphStyle("cellr", fontName="DIN", fontSize=8.8, leading=11.2, alignment=TA_RIGHT),
    "cellrb": ParagraphStyle("cellrb", fontName="DIN-B", fontSize=8.8, leading=11.2, alignment=TA_RIGHT),
    "th": ParagraphStyle("th", fontName="DIN-M", fontSize=8.3, leading=10.5),
    "thr": ParagraphStyle("thr", fontName="DIN-M", fontSize=8.3, leading=10.5, alignment=TA_RIGHT),
    "label": ParagraphStyle("label", fontName="DIN-M", fontSize=8.3, leading=11, textColor=G3),
}

WD = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MO = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
      "Dezember"]
W = A4[0] - 25 * mm - 20 * mm  # Satzspiegel (DIN 5008: links 25, rechts 20)


# ------------------------------------------------------------------------------------------- text helpers
def e(t: Any) -> str:
    """XML-escapen; Zeichen ohne D-DIN-Glyphe in der Ersatzschrift setzen."""
    s = "–" if t is None or t == "" else str(t)
    cmap, fb = _FONTS.get("cmap", set()), _FONTS.get("fb")
    if not fb or all(ord(ch) in cmap or ch in "\n\t" for ch in s):
        return escape(s)
    out, run, run_fb = [], "", False
    for ch in s:
        need_fb = ord(ch) not in cmap and ch not in "\n\t"
        if need_fb != run_fb and run:
            out.append(f'<font name="{fb}">{escape(run)}</font>' if run_fb else escape(run))
            run = ""
        run, run_fb = run + ch, need_fb
    out.append(f'<font name="{fb}">{escape(run)}</font>' if run_fb else escape(run))
    return "".join(out)


def P(t: Any, st: str = "cell") -> Paragraph:
    return Paragraph(e(t), S[st])


def PX(xml: str, st: str = "cell") -> Paragraph:
    return Paragraph(xml, S[st])


def num(x: Optional[float], d: int = 2) -> str:
    if x is None:
        return "–"
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def numsmart(x: Any) -> str:
    """Zahl ohne überflüssige Nachkommastellen (6,5 statt 6,50); Strings unverändert."""
    if x is None:
        return "–"
    if isinstance(x, str):
        return x
    s = num(x, 2)
    return s.rstrip("0").rstrip(",") if "," in s else s


def pct(x: Optional[float]) -> str:
    return "–" if x is None else f"{num(x, 0)} %"


def longdate(s: str) -> str:
    d = date.fromisoformat(s[:10])
    return f"{WD[d.weekday()]}, {d.day}. {MO[d.month - 1]} {d.year}"


def dtime(s: Optional[str]) -> str:
    return datetime.fromisoformat(s).strftime("%d.%m.%Y, %H:%M") if s else "–"


def tspan(r: Optional[dict]) -> str:
    if not r:
        return "–"
    a, b = r.get("from"), r.get("to")
    return f"{a or '?'} – {b} Uhr" if b else f"seit {a} Uhr (andauernd)"


def fmt_deviation(r: dict) -> tuple[str, str, str]:
    """(Soll, Ist, Abweichung) als Text – gemeinsam für PDF und DOCX."""
    if r.get("kind") == "finish_delay":
        dd = lambda s: date.fromisoformat(s[:10]).strftime("%d.%m.") if s else "–"  # noqa: E731
        return dd(r.get("planned")), dd(r.get("actual")), f"{r.get('delay_days', 0):+d} AT"
    unit = f" {r['unit']}" if r.get("unit") else ""
    p = r.get("deviation_pct")
    return (numsmart(r.get("planned")) + unit, numsmart(r.get("actual")) + unit,
            "–" if p is None else f"{'+' if p > 0 else ''}{num(p, 1)} %")


def orig(src: dict) -> str:
    t = e(src.get("original_text"))
    lang = src.get("original_language") or "de"
    if lang != "de":
        out = f'{t} <font color="#595959">[{e(lang.upper())}]</font>'
        if src.get("translation_de"):
            out += f'<br/><font name="DIN-M">Übersetzung (DE):</font> {e(src["translation_de"])}'
        return out
    return t


# ------------------------------------------------------------------------------------------- tables
def grid(rows: list, widths: list, header: bool = True, extra: Optional[list] = None) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
          ("LINEBELOW", (0, 0), (-1, -1), 0.4, G2), ("LINEABOVE", (0, 0), (-1, 0), 0.9, BLACK),
          ("LINEBELOW", (0, -1), (-1, -1), 0.9, BLACK)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), G1), ("LINEBELOW", (0, 0), (-1, 0), 0.9, BLACK)]
    t.setStyle(TableStyle(st + (extra or [])))
    return t


def kv(pairs: list, label_w: float = 36 * mm) -> Table:
    rows = [[P(k, "label"), v if not isinstance(v, (str, type(None))) else P(v)] for k, v in pairs]
    t = Table(rows, colWidths=[label_w, W - label_w])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2)]))
    return t


def bullets(items: list[str]) -> Paragraph:
    return PX("<br/>".join("– " + e(x) for x in items))


class _Num:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self, title: str) -> list:
        self.n += 1
        return [CondPageBreak(30 * mm), Paragraph(e(f"{self.n}  {title}"), S["h"]),
                Table([[""]], colWidths=[W], rowHeights=[0.1], style=[("LINEABOVE", (0, 0), (-1, -1), 1.2, BLACK)]),
                Spacer(1, 3)]


def signatures(labels: list[str]) -> Table:
    gap = 8 * mm
    cw = (W - gap * (len(labels) - 1)) / len(labels)
    row1, row2, widths = [], [], []
    for i, l in enumerate(labels):
        row1.append("")
        row2.append(P(l, "smallg"))
        widths.append(cw)
        if i < len(labels) - 1:
            row1.append("")
            row2.append("")
            widths.append(gap)
    t = Table([row1, row2], colWidths=widths, rowHeights=[16 * mm, None])
    st = [("TOPPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 0)]
    st += [("LINEBELOW", (i, 0), (i, 0), 0.7, BLACK) for i in range(0, len(widths), 2)]
    t.setStyle(TableStyle(st))
    return t


# ------------------------------------------------------------------------------------------- page decoration
class NumberedCanvas(rl_canvas.Canvas):
    """Zweiter Durchlauf für „Seite x von y“."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._pages: list[dict] = []

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


def _onpage(left: str, right: str):
    def draw(c, _doc):
        c.saveState()
        c.setFont("DIN-M", 8)
        c.setFillColor(BLACK)
        c.drawString(25 * mm, A4[1] - 12 * mm, left)
        c.setFont("DIN", 8)
        c.setFillColor(G3)
        c.drawRightString(A4[0] - 20 * mm, A4[1] - 12 * mm, right)
        c.setStrokeColor(BLACK)
        c.setLineWidth(0.6)
        c.line(25 * mm, A4[1] - 14 * mm, A4[0] - 20 * mm, A4[1] - 14 * mm)
        c.line(25 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
        c.drawString(25 * mm, 12 * mm, DISCLAIMER.strip())
        c.restoreState()
    return draw


# ------------------------------------------------------------------------------------------- Bautagesbericht
def story(d: dict, photo_files: dict[str, Path]) -> list:
    m = d["meta"]
    H = _Num()
    out: list = [Paragraph(e(f"Bautagesbericht Nr. {m.get('report_no') or ''}"), S["title"]),
                 Paragraph(e(longdate(m["date"])), S["subtitle"]), Spacer(1, 8)]

    cw = [30 * mm, W / 2 - 30 * mm, 30 * mm, W / 2 - 30 * mm]
    wh = m.get("working_hours") or {}
    rows = [
        [P("Bauvorhaben", "label"), P(m["project"]["name"]), P("Projekt-Nr.", "label"), P(m["project"].get("project_no"))],
        [P("Baustelle", "label"), P(m["project"].get("address")), P("Vertrag", "label"), P(m["project"].get("contract_no"))],
        [P("Auftraggeber", "label"), P(m["client"]["name"]), P("Auftragnehmer", "label"), P(m["contractor"]["company"])],
        [P("Vertreter AG", "label"), P(m["client"].get("representative")), P("Bauleitung", "label"),
         P(m["contractor"]["bauleiter"])],
        [P("Arbeitszeit", "label"), P(f"{wh.get('start', '?')} – {wh.get('end', '?')} Uhr"), P("Verfasser", "label"),
         P(m.get("author"))],
    ]
    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.9, BLACK),
                           ("LINEBELOW", (0, 0), (-1, -2), 0.4, G2), ("LINEBEFORE", (2, 0), (2, -1), 0.4, G2),
                           ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
    out.append(t)

    # 1 Witterung
    w = d.get("weather")
    out += H("Witterung")
    if w:
        rows = [[P(h, "th") for h in ["Wetter", "Temperatur min / max", "Niederschlag", "Wind", "Arbeitsfähigkeit", "Bewertung"]],
                [P(w["condition"]), P(f"{numsmart(w['temp_min_c'])} °C / {numsmart(w['temp_max_c'])} °C"),
                 P(f"{numsmart(w.get('precipitation_mm'))} mm"), P(w.get("wind")),
                 P("gegeben" if w["work_possible"] else "nicht gegeben"), P(w.get("impact_note"))]]
        out.append(grid(rows, [20 * mm, 30 * mm, 21 * mm, 24 * mm, 24 * mm, W - 119 * mm]))
    else:
        out.append(P("Keine Wetterdaten erfasst.", "smallg"))

    # 2 Personal
    out += H("Personaleinsatz")
    rows = [[P(h, "th") for h in ["Firma / Kolonne", "Gewerk", "Soll", "Ist", "Stunden", "davon Stillstand", "Belege"]]]
    wf = d["workforce"]
    for r in wf:
        ist = "–" if r["count"] is None else str(r["count"]) + (" *" if r.get("derived") else "")
        rows.append([PX(f'{e(r["crew"])}<br/><font size="7.5" color="#595959">{e(r["company"])}</font>'), P(r["trade"]),
                     P(r["planned"], "cellr"), P(ist, "cellrb" if r["count"] is not None and r["count"] < r["planned"] else "cellr"),
                     P(numsmart(r.get("hours_total")), "cellr"),
                     P(f"{numsmart(r['idle_hours'])} h" if r.get("idle_hours") else "–", "cellr"),
                     P(", ".join(r.get("source_refs", [])) or "–", "small")])
    known = [r for r in wf if r["count"] is not None]
    rows.append([P("Summe", "cellb"), P(""), P(sum(r["planned"] for r in wf), "cellrb"),
                 P(sum(r["count"] for r in known) if known else "–", "cellrb"),
                 P(numsmart(sum(r["hours_total"] or 0 for r in wf)), "cellrb"),
                 P(f"{numsmart(idle)} h" if (idle := sum(r["idle_hours"] or 0 for r in wf)) else "–", "cellrb"), P("")])
    out.append(grid(rows, [44 * mm, 24 * mm, 13 * mm, 13 * mm, 17 * mm, 22 * mm, W - 133 * mm],
                    extra=[("LINEABOVE", (0, -1), (-1, -1), 0.9, BLACK)]))
    if any(r.get("derived") for r in wf):
        out += [Spacer(1, 2), P("* nicht einzeln erfasst – aus der gemeldeten Gesamtzahl abgeleitet.", "smallg")]

    # 3 Geräte
    out += H("Geräteeinsatz")
    if d["equipment"]:
        rows = [[P(h, "th") for h in ["Gerät", "Status", "Soll h", "Ist h", "Ausfallzeit", "Ursache"]]]
        for r in d["equipment"]:
            down = "<br/>".join(e(tspan(x)) for x in r.get("downtime", [])) or "–"
            rows.append([P(r["name"]), P(r["status"], "cellb" if r["status"] != "im Einsatz" else "cell"),
                         P(numsmart(r.get("hours_planned")), "cellr"), P(numsmart(r.get("hours_operated")), "cellr"),
                         PX(down), P(r.get("downtime_cause"))])
        out.append(grid(rows, [30 * mm, 24 * mm, 13 * mm, 13 * mm, 27 * mm, W - 107 * mm]))
    else:
        out.append(P("Kein Großgerät im Tagesverlauf erfasst.", "smallg"))

    # 4 Lieferungen
    out += H("Lieferungen")
    if d.get("deliveries"):
        rows = [[P(h, "th") for h in ["Material", "Menge", "Lieferant", "durch", "Soll", "Ist", "Verzug", "Lieferschein"]]]
        for r in d["deliveries"]:
            rows.append([P(r["material"]), P(f"{numsmart(r['quantity'])} {r['unit']}", "cellr"), P(r.get("supplier")),
                         P(r["supplied_by"]), P(r.get("planned_time")), P(r.get("actual_time")),
                         P(f"{r.get('delay_minutes', 0)} min", "cellr"), P(r.get("delivery_note_no"))])
        out.append(grid(rows, [40 * mm, 17 * mm, 27 * mm, 11 * mm, 12 * mm, 12 * mm, 15 * mm, W - 134 * mm]))
    else:
        out.append(P("Keine Lieferungen erfasst.", "smallg"))

    # 5 Leistungen
    out += H("Ausgeführte Arbeiten und Leistungsstand")
    rows = [[P(h, "th") for h in ["Vorgang", "Leistung", "Tagessoll", "Ist", "Einh.", "Erfüllung", "Gesamt", "Prognose Ende"]]]
    for r in d["work_performed"]:
        name = e(r["description"]) + (' <font color="#595959">(krit. Weg)</font>' if r.get("critical") else "")
        fc = date.fromisoformat(r["forecast_finish"]).strftime("%d.%m.") if r.get("forecast_finish") else "–"
        if r.get("delay_days"):
            fc += f" ({r['delay_days']:+d} AT)"
        low = r.get("ratio_pct") is not None and r["ratio_pct"] < 100
        rows.append([P(r["activity_id"]), PX(name), P(numsmart(r["quantity_planned"]), "cellr"),
                     P(numsmart(r["quantity_actual"]), "cellr"), P(r["unit"]),
                     P(pct(r.get("ratio_pct")), "cellrb" if low else "cellr"), P(pct(r.get("progress_pct")), "cellr"),
                     P(fc, "cellb" if r.get("delay_days") else "cell")])
    out.append(grid(rows, [14 * mm, W - 122 * mm, 17 * mm, 14 * mm, 11 * mm, 17 * mm, 16 * mm, 33 * mm]))

    # 6 Soll-Ist-Abweichungen
    if d.get("deviations") or d.get("milestones_at_risk") or d.get("impact_chains"):
        out += H("Soll-Ist-Abweichungen")
        if d.get("deviations"):
            rows = [[P(h, "th") for h in ["Vorgang", "Kennzahl", "Soll", "Ist", "Abweichung", "Bewertung", "Ereignis"]]]
            for r in d["deviations"]:
                sev = r["severity"]
                strong = sev in ("hoch", "kritisch")
                soll, ist, dev = fmt_deviation(r)
                rows.append([P(r["activity_id"]), P(r["metric"]), P(soll, "cellr"), P(ist, "cellr"), P(dev, "cellrb"),
                             P(sev.upper() if strong else sev, "cellb" if strong else "cell"),
                             PX("<br/>".join(e(x) for x in r.get("linked_incident_ids", [])) or "–", "small")])
            out.append(grid(rows, [13 * mm, W - 119 * mm, 17 * mm, 17 * mm, 19 * mm, 19 * mm, 34 * mm]))
        for txt in d.get("milestones_at_risk", []):
            out += [Spacer(1, 3), PX(f'<font name="DIN-B">Meilenstein gefährdet:</font> {e(txt)}', "body")]
        for txt in d.get("impact_chains", []):
            out += [Spacer(1, 3), PX(f'<font name="DIN-B">Auswirkungskette:</font> {e(txt)}', "body")]

    # 7 Besondere Vorkommnisse
    out += H("Besondere Vorkommnisse")
    if not d["incidents"]:
        out.append(P("Keine besonderen Vorkommnisse.", "smallg"))
    for r in d["incidents"]:
        head = Table([[PX(f'<font name="DIN-B">{e(r["incident_id"])}</font>   {e(r["type"])}'),
                       P(tspan(r.get("time")), "cellr")]], colWidths=[W * 0.62, W * 0.38])
        head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), G1), ("LINEABOVE", (0, 0), (-1, 0), 0.9, BLACK),
                                  ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
        pairs: list = [("Sachverhalt", r.get("description")), ("Ursache", r.get("cause")),
                       ("Risikosphäre", PX(f'<font name="DIN-B">{e(r.get("responsibility_sphere"))}</font>  '
                                           f'({e(r.get("sphere_note"))})')),
                       ("Begründung", r.get("sphere_reasoning")),
                       ("Auswirkung", "; ".join(r.get("impact", [])) or None),
                       ("Betroffene Vorgänge", ", ".join(r.get("affected_activities", [])) or None),
                       ("Empfohlene Maßnahme", PX(f'<font name="DIN-B">{e(r.get("suggested_notice"))}</font>')),
                       ("Frist / Hinweis", r.get("notice_deadline_hint"))]
        if r.get("warnings"):
            pairs.append(("Warnung", PX("<br/>".join(f'<font name="DIN-B">{e(x)}</font>' for x in r["warnings"]))))
        pairs += [("Status", r.get("notice_status")),
                  ("Konfidenz", num(r["confidence"]) if r.get("confidence") is not None else None),
                  ("Belege", ", ".join(r.get("source_refs", [])) or None)]
        box = Table([[head], [kv(pairs)]], colWidths=[W])
        box.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                                 ("LINEBELOW", (0, -1), (-1, -1), 0.9, BLACK)]))
        out += [KeepTogether([box]), Spacer(1, 8)]

    # 8 Fotos
    if d.get("photos"):
        out += H("Fotodokumentation")
        rows = [[P(h, "th") for h in ["Foto", "Bild", "Aufnahme / Ort", "Beschreibung", "Bezug"]]]
        for r in d["photos"]:
            img: Any = P("nicht verfügbar", "smallg")
            f = photo_files.get(r["photo_id"])
            if f and f.exists():
                iw, ih = ImageReader(str(f)).getSize()
                img = Image(str(f), width=36 * mm, height=36 * mm * ih / iw)
            rows.append([P(r["photo_id"]), img, PX(f'{e(dtime(r["timestamp"]))}<br/>{e(r.get("location"))}', "small"),
                         P(r.get("caption_de")), P(", ".join(r.get("related_ids", [])) or "–", "small")])
        out.append(grid(rows, [17 * mm, 39 * mm, 27 * mm, W - 121 * mm, 38 * mm]))
        out += [Spacer(1, 2), P("Gesichter vor dem Export automatisch verpixelt (DSGVO).", "smallg")]

    # 9 Quellen
    out += H("Quellen und Belege")
    rows = [[P(h, "th") for h in ["ID", "Art", "Zeitpunkt", "Verfasser", "Inhalt"]]]
    for s in d["sources"]:
        rows.append([P(s["source_id"], "small"), P(s["type"], "small"), P(dtime(s.get("timestamp")), "small"),
                     P(s.get("author"), "small"), PX(orig(s), "small")])
    out.append(grid(rows, [25 * mm, 21 * mm, 24 * mm, 30 * mm, W - 100 * mm]))

    # 10 Prüfung
    rv = d["review"]
    out += H("Prüfung und Freigabe")
    items: list = [("Status", rv["status"])]
    if rv.get("unsupported_statements"):
        items.append(("Ohne Beleg", bullets(rv["unsupported_statements"])))
    if rv.get("uncertain"):
        items.append(("Unsicher", bullets(rv["uncertain"])))
    if rv.get("open_questions"):
        items.append(("Rückfragen", bullets(rv["open_questions"])))
    out += [kv(items), Spacer(1, 18),
            KeepTogether([signatures(["Ort, Datum", "Bauleitung Auftragnehmer", "Auftraggeber / Vertreter AG"])])]
    return out


def render(d: dict, out: Path, photo_files: Optional[dict[str, Path]] = None) -> Path:
    _register_fonts()
    m = d["meta"]
    doc = BaseDocTemplate(str(out), pagesize=A4, leftMargin=25 * mm, rightMargin=20 * mm, topMargin=20 * mm,
                          bottomMargin=22 * mm, title=f"Bautagesbericht {m['report_id']}",
                          author=m["contractor"]["company"])
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f", leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    p = m["project"]
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPageEnd=_onpage(
        f"Bautagesbericht Nr. {m.get('report_no') or ''}", f"{p['name']} · {p.get('project_no') or ''}"))])
    doc.build(story(d, photo_files or {}), canvasmaker=NumberedCanvas)
    return out
