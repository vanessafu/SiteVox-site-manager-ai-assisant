"""E-Mail-Adresse des Auftraggebers (Empfänger der Anzeigen) aus den hochgeladenen Unterlagen ermitteln.

Bewusst nur aus Belegen – nicht aus Annahmen und nicht aus den Stammdaten: Eine Anzeige an eine falsche
Adresse (z. B. Architekt oder Tragwerksplaner ohne Vollmacht) ist rechtlich wertlos. Findet sich keine
Adresse, die eindeutig dem bevollmächtigten Vertreter bzw. dem AG zuzuordnen ist, bleibt das Feld leer
und die Bauleitung muss sie eintragen.

Quellen: Dokumente (Vertrag, Protokolle …), Vertrags-/Dokumentbelege und E-Mails (Kopfzeilen + Text).
Bewertung je Fundstelle (Umfeld ±200 Zeichen):
  + Name des Vertreters, Firmenname des AG, "bevollmächtigt"/"Vertreter des AG"/"Auftraggeber", Domain passt zum AG
  − Adresse/Absender gehört zu einem Beteiligten ohne Vollmacht oder zur eigenen Firma → ausgeschlossen
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .. import settings, store

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
TITLES = {"dipl.-ing.", "dipl.-ing", "dr.", "prof.", "ing.", "herr", "frau", "mr", "ms", "b.sc.", "m.sc."}
STOP = {"gmbh", "co.", "kg", "ag", "mbh", "und", "&", "co", "des", "der", "die", "bundes", "niederlassung"}
MIN_SCORE = 4


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[\s,()/]+", (name or "").lower()) if len(t) > 2 and t not in STOP]


def _surname(rep: str) -> Optional[str]:
    parts = [p for p in re.split(r"\s+", rep or "") if p.lower() not in TITLES]
    if not parts or rep.strip().upper().startswith("N. N"):
        return None
    return parts[-1].strip(",").lower()


# Dipl.-Ing., Dr., z. B., Nr., Abs. 1.  → kein Satzende
_ABBR = re.compile(r"(?:\b[A-Za-z]|\d|\b(?:Dipl|Ing|Dr|Prof|Nr|Abs|Str|bzw|ggf|vgl|ca|inkl|zzgl|Hd|Tel|Fa|St))\.$")


def _sentence(text: str, start: int, end: int) -> str:
    """Satz um die Fundstelle; Abkürzungspunkte (Dipl.-Ing., Nr.) beenden keinen Satz."""
    a = text.rfind("\n", 0, start) + 1
    for m in re.finditer(r"\.\s", text[a:start]):
        if not _ABBR.search(text[a:a + m.start() + 1]):
            cut = a + m.end()
    a = locals().get("cut", a)
    b = len(text)
    for m in re.finditer(r"\.(\s|$)", text[end:]):
        if not _ABBR.search(text[:end + m.start() + 1]):
            b = end + m.start() + 1
            break
    nl = text.find("\n", end)
    if 0 <= nl < b:
        b = nl
    return re.sub(r"\s+", " ", text[a:b]).strip()


def find_client_email(project_id: str) -> Optional[dict[str, Any]]:
    """Beste belegte Adresse des AG oder None. Rückgabe: email, quote, source, title, doc_id/capture_id, score."""
    project = settings.project_cfg(project_id)
    client = project.get("client") or {}
    surname = _surname(client.get("representative", ""))
    client_tok = _tokens(client.get("name", ""))
    excluded = {t for p in project.get("parties", []) for t in _tokens(p.get("name", ""))}
    excluded |= set(_tokens(settings.baseline()["company"]["name"]))
    excluded -= set(client_tok)

    def score(addr: str, ctx: str) -> int:
        a, c = addr.lower(), ctx.lower()
        local, _, domain = a.partition("@")
        if any(t in domain or t in local for t in excluded):
            return -99
        s = 0
        if surname and (surname in c or surname in local):
            s += 3
        s += min(2, sum(1 for t in client_tok if t in c))
        if any(k in c for k in ("bevollmächtig", "vertreter des ag", "auftraggeber", "authorised representative")):
            s += 2
        if any(t in domain for t in client_tok):
            s += 2
        if "nicht bevollmächtigt" in c and not (surname and surname in c):
            s -= 3
        return s

    hits: list[dict] = []

    def scan(text: str, base: dict) -> None:
        for m in EMAIL_RE.finditer(text or ""):
            ctx = text[max(0, m.start() - 200): m.end() + 200]
            hits.append({**base, "email": m.group(0), "score": score(m.group(0), ctx),
                         "quote": _sentence(text, m.start(), m.end())})

    # 1) hochgeladene Dokumente (Vertrag zuerst: höchstes Gewicht als Vertragsgrundlage)
    for d in store.query("documents", "project_id=?", (project_id,)):
        text = "\n".join(p.get("text", "") for p in d.get("pages", []))
        is_contract = (d.get("collection") == "contract" or "vertrag" in (d.get("title") or "").lower())
        scan(text, {"source": "contract" if is_contract else "document", "title": d.get("title"),
                    "doc_id": d.get("doc_id"), "bonus": 1 if is_contract else 0})
    # 2) Vertrags-/Dokumentbelege (falls Text nur dort vorliegt)
    for e in store.project_evidence(project_id):
        if e["source"] in ("contract", "document"):
            scan(e.get("full_text") or e.get("quote") or "", {"source": e["source"], "title": e.get("title"),
                                                             "doc_id": (e.get("meta") or {}).get("doc_id"),
                                                             "evidence_id": e["evidence_id"], "bonus": 0})
    # 3) E-Mails: Kopfzeilen (Anzeigename + Adresse) und Text
    for m in store.emails(project_id):
        for hdr in ("from", "to", "cc"):
            for part in re.split(r",(?![^<]*>)", m.get(hdr) or ""):
                am = EMAIL_RE.search(part)
                if am:
                    hits.append({"source": "email", "title": m.get("subject"), "capture_id": m.get("capture_id"),
                                 "email": am.group(0), "score": score(am.group(0), part), "bonus": 0,
                                 "quote": f"{hdr.capitalize()}: {part.strip()} (Betreff: {m.get('subject') or '–'})"})
        scan(m.get("body") or "", {"source": "email", "title": m.get("subject"), "capture_id": m.get("capture_id"),
                                   "bonus": 0})

    best: dict[str, dict] = {}
    for h in hits:
        h["score"] += h.pop("bonus", 0)
        key = h["email"].lower()
        if key not in best or h["score"] > best[key]["score"]:
            best[key] = h
    ranked = sorted(best.values(), key=lambda h: -h["score"])
    if not ranked or ranked[0]["score"] < MIN_SCORE:
        return None
    top = ranked[0]
    # zwei gleich gute, verschiedene Adressen → nicht raten
    if len(ranked) > 1 and ranked[1]["score"] == top["score"]:
        return None
    return top
