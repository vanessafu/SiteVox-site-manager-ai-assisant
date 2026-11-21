"""GAEB (Leistungsverzeichnis-Austausch) – Import und Export über die Bibliothek `gaeb`.

Import:  GAEB DA XML 2.x–3.3 (.x81–.x89), GAEB 2000 (.p81–.p86), GAEB 90 (.d81–.d86)
         → Dokument mit Seiten je Titel, LV-Tabelle (Pos. | Kurztext | Menge | Einheit | EP) und
           strukturierten Positionen (lv_items), damit RAG-Suche und LV-Prüfung („nicht im LV“) greifen.
Export:  Positionen eines LV-Dokuments (aus GAEB importiert oder als Tabelle in PDF/DOCX/MD) → GAEB DA XML 3.3,
         Phase 81/83/84/86 (.x81/.x83/.x84/.x86).

Hinweis zur OZ: Der Writer von `gaeb` schreibt Titel-RNoPart mit 2 und Positions-RNoPart mit 4 Stellen.
Die OZ wird daher auf das Schema 2 (+2 je Untertitel) + 4 normiert, z. B. "03.010" → Titel "03", Position "0010".
"""
from __future__ import annotations

import re
import warnings
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

XML_SUFFIXES = {f".x{n}" for n in ("31", "80", "81", "82", "83", "84", "85", "86", "87", "88", "89")}
GAEB90_SUFFIXES = {f".d{n}" for n in ("81", "82", "83", "84", "85", "86")}
GAEB2000_SUFFIXES = {f".p{n}" for n in ("81", "82", "83", "84", "85", "86")}
SUFFIXES = XML_SUFFIXES | GAEB90_SUFFIXES | GAEB2000_SUFFIXES
EXPORT_PHASES = ("81", "83", "84", "86")
HEADER = ["Pos.", "Kurztext", "Menge", "Einheit", "EP"]


def is_gaeb(path: Path) -> bool:
    return Path(path).suffix.lower() in SUFFIXES


# ----------------------------------------------------------------------------- helpers
def _num(v: Any) -> Optional[Decimal]:
    """'4480' / '1.250,5' / '64 t' / Decimal → Decimal (None wenn leer/ungültig)."""
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s) if s not in ("", "-", ".") else None
    except InvalidOperation:
        return None


def _fmt(d: Optional[Decimal]) -> str:
    if d is None:
        return ""
    s = format(d.normalize(), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def _split_oz(oz: str, bkdn: list) -> str:
    """'030010' + Schema [2,4] → '03.0010' (Lesbarkeit; ohne Schema unverändert)."""
    lens = [b.laenge for b in bkdn] if bkdn else []
    if not lens or sum(lens) != len(oz):
        return oz
    out, i = [], 0
    for n in lens:
        out.append(oz[i:i + n])
        i += n
    return ".".join(out)


# ----------------------------------------------------------------------------- import
def read(path: Path):
    import gaeb

    path = Path(path)
    suf = path.suffix.lower()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if suf in GAEB90_SUFFIXES:
            return gaeb.read_gaeb90(path), "GAEB 90"
        if suf in GAEB2000_SUFFIXES:
            return gaeb.read_gaeb2000(path), "GAEB 2000"
        lv = gaeb.read_xml(path)
        return lv, f"DA XML {lv.xml_version or ''}".strip()


def _walk(titles, path: list, out: list, bkdn) -> None:
    for t in titles:
        here = path + [(t.nummer, t.kurztext)]
        for p in t.positionen:
            out.append({
                "oz": _split_oz(p.oz, bkdn), "kurztext": p.kurztext or "",
                "langtext": [x for x in (p.langtext or []) if x.strip()],
                "menge": _fmt(p.menge), "einheit": p.einheit or "", "ep": _fmt(p.einheitspreis),
                "title_nr": ".".join(n for n, _ in here), "title": " / ".join(k for _, k in here if k),
                "flags": [f for f, on in (("Pauschal", p.pauschale), ("Stundenlohn", p.stundenlohn),
                                          ("Bedarfsposition", p.provis), ("entfällt", p.entfaellt)) if on],
            })
        _walk(t.untertitel, here, out, bkdn)


def parse(path: Path) -> dict[str, Any]:
    """GAEB-Datei → {pages, tables, markdown, backend, gaeb, lv_items} (wie documents.parse)."""
    lv, fmt = read(path)
    items: list[dict] = []
    _walk(lv.titel, [], items, lv.boq_bkdn)
    pages, tables = [], []
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it["title_nr"].split(".")[0] or "–", []).append(it)
    head = [f"Leistungsverzeichnis {lv.titel_lv or Path(path).stem}",
            *(f"{k}: {v}" for k, v in (("Projekt", lv.projekt), ("Auftraggeber", lv.auftraggeber)) if v)]
    for n, (nr, its) in enumerate(groups.items(), start=1):
        lines = ([*head, *lv.vorbemerkungen, ""] if n == 1 else []) + [f"## {nr} {its[0]['title']}".rstrip()]
        rows = []
        for it in its:
            row = [it["oz"], it["kurztext"], it["menge"], it["einheit"], it["ep"]]
            rows.append(row)
            lines.append(" | ".join(x for x in row if x) + (f" ({', '.join(it['flags'])})" if it["flags"] else ""))
            lines += [f"    {x}" for x in it["langtext"]]
        pages.append({"page": n, "text": "\n".join(lines)})
        tables.append({"page": n, "header": HEADER, "rows": rows})
    if not pages:
        pages = [{"page": 1, "text": "\n".join(head + ["(keine Positionen)"])}]
    phase = lv.phase.value if lv.phase is not None else None
    return {"pages": pages, "tables": tables, "markdown": "\n\n".join(p["text"] for p in pages), "backend": "gaeb",
            "gaeb": {"format": fmt, "phase": phase, "positions": len(items), "projekt": lv.projekt,
                     "auftraggeber": lv.auftraggeber, "titel_lv": lv.titel_lv},
            "lv_items": items}


# ----------------------------------------------------------------------------- export
def _col(header: list[str], *names: str) -> Optional[int]:
    h = [re.sub(r"[^a-zäöü]", "", str(x).lower()) for x in header]
    for n in names:
        for i, x in enumerate(h):
            if x.startswith(n):
                return i
    return None


def items_from_tables(tables: list[dict]) -> list[dict]:
    """LV-Tabellen (Pos./OZ | Kurztext | Menge | Einheit [| EP]) → Positionen. Andere Tabellen werden ignoriert."""
    out = []
    for t in tables or []:
        hd = t.get("header") or []
        i_oz, i_kt = _col(hd, "pos", "oz", "ordnungszahl"), _col(hd, "kurztext", "bezeichnung", "leistung", "text")
        if i_oz is None or i_kt is None:
            continue
        i_m, i_e, i_ep = _col(hd, "menge"), _col(hd, "einheit", "me"), _col(hd, "ep", "einheitspreis")
        for r in t.get("rows") or []:
            g = lambda i: str(r[i]).strip() if i is not None and i < len(r) and r[i] is not None else ""  # noqa: E731
            if not g(i_oz) or not g(i_kt):
                continue
            out.append({"oz": g(i_oz), "kurztext": g(i_kt), "langtext": [], "menge": g(i_m), "einheit": g(i_e),
                        "ep": g(i_ep), "title_nr": "", "title": ""})
    return out


def doc_items(doc: dict) -> list[dict]:
    return doc.get("lv_items") or items_from_tables(doc.get("tables") or [])


def _oz_parts(oz: str) -> tuple[list[str], str]:
    parts = [p for p in re.split(r"[.\s/]+", oz.strip()) if p]
    if len(parts) >= 2:
        return parts[:-1], parts[-1]
    s = re.sub(r"\W", "", oz)
    return ([s[:2]], s[2:] or "1") if len(s) > 2 else (["01"], s or "1")


def to_lv(items: list[dict], *, phase: str, titel_lv: str = "", projekt: str = "", auftraggeber: str = "",
          auftragnehmer: str = "", title_names: Optional[dict[str, str]] = None):
    """Positionen → gaeb.Leistungsverzeichnis (OZ-Schema: 2 je Titelebene + 4 Position)."""
    from gaeb import BoQBkdn, Leistungsverzeichnis, Phase, Position, Titel

    parsed = [(_oz_parts(it["oz"]), it) for it in items]
    depth = max((len(lv) for (lv, _), _ in parsed), default=1)
    roots: dict[str, Any] = {}
    names = title_names or {}
    for (levels, item_nr), it in parsed:
        levels = [re.sub(r"\W", "", x).zfill(2)[-2:] for x in levels]
        levels = (levels + ["01"] * depth)[:depth]  # einheitliche Tiefe für ein gültiges BoQBkdn
        node, key = None, ""
        src_titles = [x for x in (it.get("title") or "").split(" / ") if x]
        for d, lvl in enumerate(levels):
            key = f"{key}.{lvl}" if key else lvl
            bucket = roots if node is None else node["sub"]
            if lvl not in bucket:
                kt = names.get(key) or (src_titles[d] if d < len(src_titles) else f"Titel {key}")
                bucket[lvl] = {"nr": lvl, "kt": kt, "pos": [], "sub": {}}
            node = bucket[lvl]
        menge, ep = _num(it.get("menge")), _num(it.get("ep"))
        lump = (it.get("einheit") or "").lower() in ("psch", "pauschal", "pausch")
        node["pos"].append(Position(
            oz="".join(levels) + re.sub(r"\W", "", item_nr).zfill(4)[-4:], kurztext=it["kurztext"][:300],
            langtext=list(it.get("langtext") or []), einheit=it.get("einheit") or "", menge=menge,
            einheitspreis=ep if phase in ("84", "86") else None, pauschale=lump))

    def build(n: dict):
        return Titel(nummer=n["nr"], kurztext=n["kt"], positionen=n["pos"], untertitel=[build(s) for s in n["sub"].values()])

    return Leistungsverzeichnis(
        phase=Phase(phase), titel_lv=titel_lv, projekt=projekt, auftraggeber=auftraggeber,
        auftragnehmer=auftragnehmer if phase in ("84", "86") else "",
        boq_bkdn=[BoQBkdn(typ="BoQLevel", laenge=2) for _ in range(depth)] + [BoQBkdn(typ="Item", laenge=4)],
        titel=[build(n) for n in roots.values()])


def export(doc: dict, out_dir: Path, *, phase: str = "83", project: Optional[dict] = None,
           company: Optional[dict] = None) -> Path:
    """LV-Dokument → GAEB DA XML 3.3 (.x<phase>). Wirft ValueError, wenn das Dokument keine LV-Positionen hat."""
    import gaeb

    if phase not in EXPORT_PHASES:
        raise ValueError(f"Phase {phase} nicht unterstützt ({', '.join(EXPORT_PHASES)})")
    items = doc_items(doc)
    if not items:
        raise ValueError("Dokument enthält keine LV-Positionen (Tabelle mit Pos./Kurztext/Menge/Einheit)")
    project, company = project or {}, company or {}
    titles: dict[str, str] = {}
    for p in doc.get("pages") or []:  # Titelnamen aus "## 03 Beton"-Zeilen (GAEB-Import / Markdown)
        for m in re.finditer(r"(?m)^##\s+([\d.]+)\s+(.+)$", p.get("text", "")):
            titles.setdefault(m.group(1).split(" / ")[0], m.group(2).split(" / ")[0].strip())
    lv = to_lv(items, phase=phase, titel_lv=(doc.get("gaeb") or {}).get("titel_lv") or doc.get("title", "LV"),
               projekt=project.get("title") or project.get("name", ""),
               auftraggeber=(project.get("client") or {}).get("name", ""), auftragnehmer=company.get("name", ""),
               title_names=titles)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]+", "_", doc.get("title") or "LV")[:60]
    path = out_dir / f"{safe}.x{phase}"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gaeb.write_xml(lv, path, prog_system="SiteVox")
    return path
