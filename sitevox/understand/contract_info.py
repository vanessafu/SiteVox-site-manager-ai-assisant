"""Schlüsselangaben aus einem hochgeladenen Bauvertrag lesen (regelbasiert, läuft ohne GPU/LLM).

Erkannt werden: Vertragsnummer, Vertragsdatum, Bauvorhaben + Adresse der Baustelle, Auftraggeber (Firma + Adresse),
bevollmächtigter Vertreter des AG (Name, Funktion, E-Mail, Telefon), Vertragsgrundlage, Vertragsfristen und
Beteiligte, die ausdrücklich NICHT bevollmächtigt sind. Jede Angabe trägt die Fundstelle (Satz + Seite).

Übernahme in die Stammdaten (`apply`): nur leere Felder bzw. Platzhalter („N. N.“) werden automatisch gefüllt –
was die Bauleitung schon eingetragen hat, wird nie überschrieben; Abweichungen erscheinen als Vorschlag.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from .. import settings, store

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
PHONE_RE = re.compile(r"(?:Tel(?:efon)?\.?|Fon|Mobil|Handy|Phone)\s*:?\s*(\+?[\d][\d\s/()\-]{5,}\d)", re.I)
ADDR_RE = re.compile(r"([A-ZÄÖÜ][\wÄÖÜäöüß.\- ]*?(?:straße|strasse|str\.|allee|weg|platz|ring|gasse|damm|ufer|chaussee)"
                     r"\s*\d+\s*[a-z]?(?:\s*[-–]\s*\d+)?,\s*\d{5}\s+[A-ZÄÖÜ][\wÄÖÜäöüß.\- ]+)", re.I)
PERSON_RE = re.compile(r"((?:(?:Dipl\.-Ing\.|Dipl\.-Kfm\.|Dr\.(?:-Ing\.)?|Prof\.|Herrn?|Frau|M\.\s?Sc\.|B\.\s?Eng\.)\s+)*)"
                       r"([A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?\s+[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?)")
OFFICE_RE = re.compile(r"((?:Architektur|Ingenieur|Planungs|Vermessungs|Statik)?[Bb]üro\s+[A-ZÄÖÜ][\wäöüß\-]+"
                       r"(?:\s+(?:GmbH|PartG(?:\s?mbB)?|AG|KG))?)(?:\s*\(([^)]+)\))?")
DATE_RE = r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})"


def _iso(m: re.Match) -> Optional[str]:
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date().isoformat()
    except ValueError:
        return None


def _hit(value: Any, quote: str, page: int) -> dict:
    return {"value": value, "quote": re.sub(r"\s+", " ", quote).strip()[:400], "page": page}


def _sentences(text: str) -> list[str]:
    # Abkürzungen (Dipl.-Ing., Nr., Abs.) nicht als Satzende werten
    protected = re.sub(r"\b(Dipl|Ing|Dr|Prof|Nr|Abs|Str|bzw|ggf|ca|inkl|Tel|Fa|z\.\s?B)\.", r"\1§DOT§", text)
    parts = re.split(r"(?<=[.!?])\s+|\n+", protected)
    return [p.replace("§DOT§", ".").strip() for p in parts if p.strip()]


def extract(doc: dict) -> dict[str, dict]:
    """Angaben aus einem Vertragsdokument (Seiten mit Text). Nur gefundene Felder sind im Ergebnis."""
    out: dict[str, dict] = {}

    def put(key: str, value: Any, quote: str, page: int) -> None:
        if value and key not in out:
            out[key] = _hit(value, quote, page)

    for page in doc.get("pages", []):
        text, pno = page.get("text") or "", page.get("page") or 1
        for line in text.splitlines():
            l = line.strip()
            m = re.search(r"(?:Bau)?[Vv]ertrag\s*(?:Nr\.?|Nummer)\s*:?\s*([A-Z0-9][A-Z0-9\-/.]{2,}[A-Z0-9])", l) \
                or re.search(r"Vertragsnummer\s*:?\s*([A-Z0-9][A-Z0-9\-/.]{2,}[A-Z0-9])", l)
            if m:
                put("contract_no", m.group(1), l, pno)
            m = re.search(r"Vertragsdatum\s*:?\s*" + DATE_RE, l) or re.search(r"Vertrag\b.*?\bvom\s+" + DATE_RE, l)
            if m:
                put("contract_date", _iso(m), l, pno)
            m = re.match(r"(?:Bauvorhaben|Baumaßnahme|Projekt)\s*:\s*(.+)", l)
            if m:
                rest = m.group(1).strip()
                a = ADDR_RE.search(rest)
                put("title", rest[:a.start()].strip(" ,;") if a else rest, l, pno)
                if a:
                    put("address", a.group(1).strip(), l, pno)
            m = re.match(r"Auftraggeber(?:\s*\(AG\))?\s*:\s*(.+)", l)
            if m:
                rest = m.group(1).strip()
                a = ADDR_RE.search(rest)
                put("client.name", rest[:a.start()].strip(" ,;") if a else rest.split(",")[0].strip(), l, pno)
                if a:
                    put("client.address", a.group(1).strip(), l, pno)
            m = re.match(r"Vertragsgrundlage[n]?\s*:\s*(.+)", l)
            if m and "VOB/B" in m.group(1):
                v = "VOB/B (aktuelle Fassung) als Vertragsbestandteil vereinbart" if "aktuell" in m.group(1).lower() \
                    else re.search(r"VOB/B[^,;.]*", m.group(1)).group(0).strip() + " als Vertragsbestandteil vereinbart"
                put("contract_basis", v, l, pno)
        for s in _sentences(text):
            low = s.lower()
            if "bevollmächtigt" in low and "nicht bevollmächtigt" not in low and ("vertreter" in low or "auftraggeber" in low
                                                                              or " ag" in low):
                p = PERSON_RE.search(s[low.find("ist "):] if "ist " in low else s)
                if p:
                    name = (p.group(1) + p.group(2)).strip()
                    put("client.representative", name, s, pno)
                    after = s[s.find(p.group(2)) + len(p.group(2)):]
                    r = re.match(r"\s*\(([^)]+)\)", after)
                    if r:
                        put("client.representative_role", f"{r.group(1)}, bevollmächtigter Vertreter des AG", s, pno)
                e = EMAIL_RE.search(s)
                if e:
                    put("client.email", e.group(0), s, pno)
                t = PHONE_RE.search(s)
                if t:
                    put("client.phone", re.sub(r"\s+", " ", t.group(1)).strip(), s, pno)
            if "nicht bevollmächtigt" in low:
                parties = [{"name": o.group(1).strip(), "role": f"{o.group(2) or 'Beteiligter'} (nicht bevollmächtigt)"}
                           for o in OFFICE_RE.finditer(s)]
                if parties:
                    put("parties", parties, s, pno)
            for m in re.finditer(r"(Vertragsfrist[^:.;]*?|Fertigstellungstermin[^:.;]*?|Fertigstellung[^:.;]*?)\s*:\s*" + DATE_RE, s):
                iso = _iso(re.match(r".*?" + DATE_RE, m.group(0)))
                if iso:
                    ms = out.setdefault("milestones", _hit([], s, pno))
                    if not any(x["date"] == iso for x in ms["value"]):
                        ms["value"].append({"id": f"M{len(ms['value']) + 1}", "name": m.group(1).strip(), "date": iso,
                                            "contractual": True})
    if "milestones" in out and not out["milestones"]["value"]:
        out.pop("milestones")
    return out


def _empty(v: Any) -> bool:
    return v in (None, "", [], {}) or (isinstance(v, str) and v.strip().upper().startswith("N. N"))


def _get(p: dict, key: str) -> Any:
    cur: Any = p
    for k in key.split("."):
        cur = (cur or {}).get(k)
    return cur


def compare(project_id: str) -> dict[str, Any]:
    """Erkannte Vertragsangaben ↔ Stammdaten: was übernommen werden kann (leer) und was abweicht."""
    p = settings.project_cfg(project_id)
    found: dict[str, dict] = {}
    for d in store.query("documents", "project_id=?", (project_id,)):
        if d.get("kind") == "vertrag" or "vertrag" in (d.get("title") or "").lower():
            for k, v in extract(d).items():
                found.setdefault(k, {**v, "doc_id": d["doc_id"], "doc_title": d.get("title")})
    rows = []
    for k, v in found.items():
        cur = _get(p, k)
        state = "same" if cur == v["value"] else ("empty" if _empty(cur) else "differs")
        rows.append({"key": k, "value": v["value"], "current": cur, "state": state, "quote": v["quote"],
                     "page": v["page"], "doc_id": v["doc_id"], "doc_title": v["doc_title"]})
    return {"fields": rows}


def apply(project_id: str, keys: Optional[list[str]] = None, actor: str = "ai", only_empty: bool = True) -> list[str]:
    """Erkannte Angaben in die Stammdaten übernehmen. Standard (nach Upload): nur leere Felder/Platzhalter.
    Mit `keys` übernimmt die Bauleitung gezielt auch abweichende Werte."""
    p = dict(settings.project_cfg(project_id))
    p["client"] = dict(p.get("client") or {})
    changed = []
    for r in compare(project_id)["fields"]:
        if r["state"] == "same" or (keys is not None and r["key"] not in keys):
            continue
        if only_empty and keys is None and r["state"] != "empty":
            continue
        if "." in r["key"]:
            a, b = r["key"].split(".", 1)
            p[a][b] = r["value"]
            if r["key"] == "client.email":
                p[a]["email_source"] = "contract"
        else:
            p[r["key"]] = r["value"]
        changed.append(r["key"])
    if changed:
        store.save_project(p)
        store.audit(actor, "project", project_id, "contract_info_apply", after={k: _get(p, k) for k in changed})
    return changed
