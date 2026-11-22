"""Bautagesbericht (PDF/DOCX/MD) → strukturierte Angaben für die Wissensbasis.

Liest den Seitentext (Tabellenzellen durch Tabulator getrennt, siehe pdf_layout) und gliedert ihn nach den
nummerierten Abschnitten des Berichts. Ohne Spalteninformation (reiner Text) werden nur Kopf, Datum und
Vorkommnisse erkannt. Regelbasiert, keine KI.
"""
from __future__ import annotations

import re
from typing import Any, Optional

MONTHS = {m: i for i, m in enumerate(["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
                                      "september", "oktober", "november", "dezember"], start=1)}
SECTION_RE = re.compile(r"^(\d{1,2})\s+([A-ZÄÖÜ][^\t]{2,60})$")
EVENT_RE = re.compile(r"^((?:EVT|EV)-[\w-]+)\s+(.+)$")
NOISE_RE = re.compile(r"^(Bautagesbericht Nr\.\s*\d+\t|Entwurf – keine Rechtsberatung)")


def is_daily_report(doc: dict) -> bool:
    first = " ".join((p.get("text") or "")[:400] for p in doc.get("pages", [])[:1])
    return bool(re.search(r"Bautagesbericht|Bautagebuch|Daily (site )?report", first, re.I)) \
        or doc.get("kind") == "bautagesbericht"


def _num(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", s.replace(".", "") if re.search(r"\d\.\d{3}", s) else s)
    return float(m.group(0).replace(",", ".")) if m else None


def _date(text: str) -> Optional[str]:
    m = re.search(r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s+(\d{4})", text)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text)
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def _lines(doc: dict) -> list[str]:
    out = []
    for i, p in enumerate(doc.get("pages", [])):
        for l in (p.get("text") or "").splitlines():
            if not l.strip() or (i and NOISE_RE.match(l)) or NOISE_RE.match(l) and "Entwurf" in l:
                continue
            out.append(l.rstrip())
    return out


def extract(doc: dict) -> dict[str, Any]:
    lines = _lines(doc)
    text = "\n".join(lines)
    info: dict[str, Any] = {"type": "bautagesbericht", "report_no": None, "date": _date(text[:600]),
                            "head": [], "sections": [], "summary": {}}
    m = re.search(r"Bautagesbericht\s+Nr\.?\s*(\d+)", text)
    info["report_no"] = m.group(1) if m else None

    cur: Optional[dict] = None
    table: Optional[dict] = None
    item: Optional[dict] = None
    for l in lines:
        sm = SECTION_RE.match(l.strip())
        if sm and "\t" not in l:
            cur = {"no": int(sm.group(1)), "title": sm.group(2).strip(), "tables": [], "items": [], "notes": [],
                   "fields": []}
            info["sections"].append(cur)
            table = item = None
            continue
        cells = [c.strip() for c in l.split("\t")]
        if cur is None:  # Kopf: „Bauvorhaben | … | Projekt-Nr. | …“ als Paare
            if len(cells) >= 2 and len(cells) % 2 == 0 and not l.startswith("Bautagesbericht"):
                info["head"] += [{"label": cells[i], "value": cells[i + 1]} for i in range(0, len(cells), 2)]
            continue
        em = EVENT_RE.match(cells[0])
        if em:
            item = {"id": em.group(1), "title": em.group(2), "when": cells[1] if len(cells) > 1 else "", "fields": {}}
            cur["items"].append(item)
            table = None
            continue
        if item is not None and len(cells) == 2:
            item["fields"][cells[0]] = cells[1]
            continue
        if len(cells) == 2 and not any(re.search(r"\d", c) for c in cells[:1]) and table is None \
                and len(cells[0]) < 30:
            cur["fields"].append({"label": cells[0], "value": cells[1]})
            continue
        if len(cells) >= 3:
            if table is None:
                table = {"header": cells, "rows": []}
                cur["tables"].append(table)
            else:
                table["rows"].append(cells)
            continue
        table = None
        if l.strip():
            if cur["notes"] and not re.match(r"^[A-ZÄÖÜ*]", l.strip()):
                cur["notes"][-1] += " " + l.strip()
            else:
                cur["notes"].append(l.strip())

    info["summary"] = _summary(info)
    return info


def _section(info: dict, *words: str) -> Optional[dict]:
    return next((s for s in info["sections"] if any(w.lower() in s["title"].lower() for w in words)), None)


def _col(table: dict, *names: str) -> Optional[int]:
    for i, h in enumerate(table["header"]):
        if any(h.lower().startswith(n.lower()) for n in names):
            return i
    return None


def _summary(info: dict) -> dict[str, Any]:
    s: dict[str, Any] = {}
    wx = _section(info, "Witterung", "Wetter")
    if wx and wx["tables"] and wx["tables"][0]["rows"]:
        t = wx["tables"][0]
        s["weather"] = {h: v for h, v in zip(t["header"], t["rows"][0])}
    staff = _section(info, "Personal")
    if staff and staff["tables"]:
        t = staff["tables"][0]
        i_soll, i_ist, i_h = _col(t, "Soll"), _col(t, "Ist"), _col(t, "Stunden")
        crews = [r for r in t["rows"] if not r[0].lower().startswith("summe")]
        total = next((r for r in t["rows"] if r[0].lower().startswith("summe")), None)
        # Summenzeile hat eine Zelle weniger (Gewerk leer) → von rechts lesen
        if total and i_ist is not None:
            off = len(t["header"]) - len(total)
            s["staff"] = {"planned": _num(total[i_soll - off]) if i_soll is not None else None,
                          "actual": _num(total[i_ist - off]), "hours": _num(total[i_h - off]) if i_h is not None else None}
        elif i_ist is not None:
            s["staff"] = {"planned": sum(_num(r[i_soll]) or 0 for r in crews) if i_soll is not None else None,
                          "actual": sum(_num(r[i_ist]) or 0 for r in crews), "hours": None}
        s["crews"] = len(crews)
    eq = _section(info, "Gerät")
    if eq and eq["tables"]:
        t = eq["tables"][0]
        i_st = _col(t, "Status")
        s["equipment_down"] = [r[0] for r in t["rows"] if i_st is not None and r[i_st] and r[i_st] != "im Einsatz"]
        s["equipment"] = len(t["rows"])
    dl = _section(info, "Lieferung")
    if dl:
        s["deliveries"] = sum(len(t["rows"]) for t in dl["tables"])
    work = _section(info, "Ausgeführte Arbeiten", "Leistung")
    if work and work["tables"]:
        t = work["tables"][0]
        i_end = _col(t, "Prognose")
        s["delayed_activities"] = [f"{r[0]} {r[1]}".strip() for r in t["rows"]
                                   if i_end is not None and "+" in r[i_end]]
    dev = _section(info, "Abweichung")
    if dev:
        s["milestones_at_risk"] = [n for n in dev["notes"] if n.startswith("Meilenstein")]
    inc = _section(info, "Vorkommnis", "Ereignis")
    if inc:
        s["events"] = [{"id": it["id"], "title": it["title"], "when": it["when"],
                        "sphere": (it["fields"].get("Risikosphäre") or "").split(" ")[0] or None,
                        "measure": it["fields"].get("Empfohlene Maßnahme"), "status": it["fields"].get("Status")}
                       for it in inc["items"]]
    return s
