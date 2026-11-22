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


def _doc_text(d: dict) -> str:
    """Seitentext; Zeilenumbrüche aus PDFs verbunden (sonst zerfällt z. B. „wohnbau-|riem.example“)."""
    from .contract_info import _unwrap

    return _unwrap("\n".join(p.get("text", "") for p in d.get("pages", [])))


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
        text = _doc_text(d)
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


# ============================================================================ Kontakte des Projekts
PHONE_RE = re.compile(r"(?:Tel(?:efon)?\.?|Fon|Mobil|Handy|Phone)\s*:?\s*(\+?\d[\d\s/()\-]{5,}\d)", re.I)
PERSON_RE = re.compile(r"(?:(?:Dipl\.-Ing\.|Dr\.(?:-Ing\.)?|Prof\.|Herrn?|Frau)\s+)*"
                       r"([A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?\s+[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?)")
AUTH_LABEL = {"authorized": "bevollmächtigt", "not_authorized": "nicht bevollmächtigt"}
FIELDS = ("name", "company", "role", "email", "phone", "address", "authority", "note")


def contact_id(c: dict) -> str:
    base = (c.get("email") or c.get("name") or c.get("company") or "kontakt").lower()
    base = base.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return "K-" + re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:60]


ORG_WORDS = re.compile(r"büro|gmbh|ag|kg|architekt|ingenieur|planung|bau|verwaltung|amt|stadt|gesellschaft", re.I)


def _is_person(text: Optional[str]) -> bool:
    return bool(text and PERSON_RE.fullmatch(text.strip()) and not ORG_WORDS.search(text))


def _name_for(addr: str, ctx: str) -> Optional[str]:
    """Person zur Adresse: Name im Satz, dessen Nachname im lokalen Teil der Adresse steckt (t.wagner → Wagner)."""
    local = addr.split("@")[0].lower()
    for m in PERSON_RE.finditer(ctx):
        if m.group(1).split()[-1].lower() in local and _is_person(m.group(1)):
            return m.group(0).strip()
    return None


def all_contacts(project_id: str) -> list[dict[str, Any]]:
    """Alle Personen/Firmen mit Kontaktdaten aus Stammdaten, Vertrag, Dokumenten und E-Mails des Projekts.

    Je Kontakt: Name, Firma, Funktion, E-Mail, Telefon, Adresse, Vollmacht (bevollmächtigt / nicht / unbekannt),
    Fundstellen. Eigene Firma ausgenommen. Manuelle Kontakte/Korrekturen (Projekt-Dokument "contacts") gehen vor,
    ausgeblendete ("contacts_hidden") fallen weg. `recommended` = Adresse, die für Anzeigen vorgeschlagen wird.
    """
    from . import contract_info

    project = settings.project_cfg(project_id)
    client = project.get("client") or {}
    company = settings.baseline()["company"]
    own = set(_tokens(company["name"]))
    party_tok = {p["name"]: set(_tokens(p["name"])) for p in project.get("parties", [])}
    client_tok = set(_tokens(client.get("name", "")))
    by_key: dict[str, dict] = {}

    def add(c: dict, src: Optional[dict]) -> None:
        if c.get("email"):
            c["email"] = c["email"].strip().rstrip(".").lower()
            local, _, dom = c["email"].partition("@")
            if any(t in dom or t in local for t in own):
                return  # eigene Firma
        key = c["email"] if c.get("email") else (c.get("name") or c.get("company") or "").lower()
        if not key:
            return
        cur = by_key.setdefault(key, {k: None for k in FIELDS} | {"sources": []})
        for k in FIELDS:
            if c.get(k) and not cur.get(k):
                cur[k] = c[k]
        if c.get("authority") == "authorized":
            cur["authority"] = "authorized"
        if src and not any(s.get("quote") == src.get("quote") and s.get("title") == src.get("title")
                           for s in cur["sources"]):
            cur["sources"].append(src)

    def company_of(addr: str, ctx: str) -> tuple[Optional[str], Optional[str]]:
        dom = addr.split("@")[-1].lower()
        for name, toks in party_tok.items():
            if any(t in dom for t in toks):
                return name, "not_authorized"
        if client_tok and any(t in dom for t in client_tok):
            return client.get("name"), None
        return None, None

    # 1) Stammdaten
    src_master = {"source": "master", "title": "Projekt-Stammdaten", "quote": None}
    rep = client.get("representative")
    if rep and not rep.strip().upper().startswith("N. N"):
        add({"name": rep, "company": client.get("name"), "role": client.get("representative_role") or "Vertreter des AG",
             "email": client.get("email") if client.get("email_source") in ("manual", "contract") else None,
             "phone": client.get("phone"), "address": client.get("address"), "authority": "authorized"}, src_master)
    elif client.get("email") and client.get("email_source") == "manual":
        add({"company": client.get("name"), "role": "Auftraggeber", "email": client["email"],
             "address": client.get("address")}, src_master)
    if client.get("name") and not client["name"].strip().upper().startswith("N. N"):
        add({"company": client["name"], "role": "Auftraggeber", "address": client.get("address")}, src_master)
    for p in project.get("parties", []):
        add({"company": p["name"], "role": p.get("role"), "email": p.get("email"),
             "authority": "not_authorized" if "vollmacht" in (p.get("role") or "").lower()
             or "nicht bevollmächtigt" in (p.get("role") or "").lower() else None}, src_master)

    # 2) Vertrag (strukturiert erkannt)
    for d in store.query("documents", "project_id=?", (project_id,)):
        if not (d.get("kind") == "vertrag" or "vertrag" in (d.get("title") or "").lower()):
            continue
        info = contract_info.extract(d)

        def src(k: str) -> dict:
            return {"source": "contract", "title": d.get("title"), "doc_id": d["doc_id"],
                    "quote": info[k]["quote"], "page": info[k]["page"]}

        val = lambda k: (info.get(k) or {}).get("value")  # noqa: E731
        if "client.representative" in info:
            add({"name": val("client.representative"), "company": val("client.name"),
                 "role": val("client.representative_role"), "email": val("client.email"), "phone": val("client.phone"),
                 "address": val("client.address"), "authority": "authorized"}, src("client.representative"))
        for p in val("parties") or []:
            add({"company": p["name"], "role": p["role"], "authority": "not_authorized"}, src("parties"))

    # 3) Adressen in Dokumenten und E-Mails (Kopfzeilen + Text)
    def scan(text: str, base: dict) -> None:
        for m in EMAIL_RE.finditer(text or ""):
            sent = _sentence(text, m.start(), m.end())
            comp, auth = company_of(m.group(0), sent)
            ph = PHONE_RE.search(sent)
            add({"email": m.group(0), "name": _name_for(m.group(0), sent), "company": comp, "authority": auth,
                 "phone": re.sub(r"\s+", " ", ph.group(1)) if ph else None}, {**base, "quote": sent})

    for d in store.query("documents", "project_id=?", (project_id,)):
        scan(_doc_text(d),
             {"source": "document", "title": d.get("title"), "doc_id": d.get("doc_id")})
    for m in store.emails(project_id):
        for hdr in ("from", "to", "cc"):
            for part in re.split(r",(?![^<]*>)", m.get(hdr) or ""):
                am = EMAIL_RE.search(part)
                if not am:
                    continue
                disp = part[:part.find("<")].strip().strip('"') if "<" in part else None
                comp, auth = company_of(am.group(0), disp or "")
                person = disp if _is_person(disp) else None
                add({"email": am.group(0), "name": person, "company": comp or (disp if disp and not person else None),
                     "authority": auth},
                    {"source": "email", "title": m.get("subject"), "capture_id": m.get("capture_id"),
                     "quote": f"{hdr.capitalize()}: {part.strip()}"})
        scan(m.get("body") or "", {"source": "email", "title": m.get("subject"), "capture_id": m.get("capture_id")})

    # Einträge ohne Adresse mit passender Adresse zusammenführen (Vertreter aus Stammdaten ↔ t.wagner@…,
    # Büro aus dem Vertrag ↔ info@lechner-architekten…)
    for key in [k for k, c in by_key.items() if not c["email"]]:
        c = by_key[key]
        sur = c["name"].split()[-1].lower() if c["name"] else None
        comp = set(_tokens(c["company"] or "")) if not c["name"] else set()
        for other in by_key.values():
            if not other["email"] or other is c:
                continue
            local, dom = other["email"].split("@")
            same_person = sur and (sur in local or (other["name"] or "").lower().endswith(sur))
            same_office = comp and not other["name"] and any(t in dom for t in comp)
            if same_person or same_office:
                for k in ("name", "company", "role", "phone", "address", "note"):
                    other[k] = other[k] or c[k]
                if c["authority"] == "authorized" or not other["authority"]:
                    other["authority"] = c["authority"] or other["authority"]
                other["sources"] = c["sources"] + other["sources"]
                by_key.pop(key)
                break

    # manuelle Kontakte / Korrekturen, Ausblendungen
    pdoc = store.get("projects", project_id) or {}
    manual = {c["id"]: c for c in pdoc.get("contacts", [])}
    hidden = set(pdoc.get("contacts_hidden", []))
    best = find_client_email(project_id)
    out = []
    for c in by_key.values():
        c["id"] = contact_id(c)
        if c["id"] in hidden:
            continue
        if c["id"] in manual:
            c.update({k: v for k, v in manual.pop(c["id"]).items() if k in FIELDS}, manual=True)
        out.append(c)
    out += [{**{k: None for k in FIELDS}, **m, "sources": [], "manual": True}
            for m in manual.values() if m["id"] not in hidden]
    for c in out:
        c["recommended"] = bool(best and c.get("email") == best["email"].lower())
        c["authority_label"] = AUTH_LABEL.get(c.get("authority"))
    rank = {"authorized": 0, None: 1, "not_authorized": 2}
    out.sort(key=lambda c: (not c["recommended"], rank.get(c.get("authority"), 1), not c.get("email"),
                            (c.get("company") or c.get("name") or "").lower()))
    return out


def save_contact(project_id: str, data: dict, actor: str, contact_id_: Optional[str] = None) -> dict:
    """Kontakt anlegen oder korrigieren (überschreibt die erkannten Angaben dieses Kontakts)."""
    p = dict(store.get("projects", project_id) or settings.project_cfg(project_id))
    c = {k: (data.get(k) or "").strip() or None for k in FIELDS}
    if not (c["name"] or c["company"] or c["email"]):
        raise ValueError("Name, Firma oder E-Mail angeben")
    if c["email"] and not EMAIL_RE.fullmatch(c["email"]):
        raise ValueError(f"Keine gültige E-Mail-Adresse: {c['email']}")
    if c["authority"] not in (None, "authorized", "not_authorized"):
        raise ValueError("authority muss authorized, not_authorized oder leer sein")
    c["id"] = contact_id_ or contact_id(c)
    p["contacts"] = [x for x in p.get("contacts", []) if x["id"] != c["id"]] + [c]
    p["contacts_hidden"] = [h for h in p.get("contacts_hidden", []) if h != c["id"]]
    store.save_project(p)
    store.audit(actor, "contact", c["id"], "save", after=c)
    return c


def hide_contact(project_id: str, contact_id_: str, actor: str) -> None:
    """Kontakt entfernen: manuelle Einträge werden gelöscht, erkannte ausgeblendet."""
    p = dict(store.get("projects", project_id) or settings.project_cfg(project_id))
    p["contacts"] = [x for x in p.get("contacts", []) if x["id"] != contact_id_]
    p["contacts_hidden"] = sorted(set(p.get("contacts_hidden", [])) | {contact_id_})
    store.save_project(p)
    store.audit(actor, "contact", contact_id_, "hide")
