"""Faktenprüfung: Jede Zahl, jedes Datum, jede Uhrzeit und jeder Firmen-/Personenname in den vom LLM
geschriebenen Sätzen muss in den Belegen vorkommen. Sonst → rot, Export gesperrt bis zur manuellen Bestätigung.

Zusätzlich:
  * jeder Satz braucht >= 1 gültige Beleg-ID [E-xx]
  * Normzitate (§, VOB, BGB) sind im LLM-Text verboten – sie kommen nur aus der Vorlage
  * KI-Beobachtungen aus Fotos (source="ai_vision") sind KEIN Beleg: Sie zählen weder für Zahlen/Daten/Namen
    noch als Zitat. Stützt sich ein Satz nur auf KI-Beobachtungen → gelb ("needs_confirmation"), Freigabe erst
    nach Bestätigung. Als Beleg gilt eine KI-Beobachtung erst, wenn die Bauleitung sie bestätigt hat oder die
    Sprach-/Textantwort sie stützt (meta.status "confirmed" bzw. "corroborated").
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

from . import settings
from .schemas import VerificationIssue

MONTHS = {m: i + 1 for i, m in enumerate(
    ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november",
     "dezember"])}
NUM_WORDS = {
    "null": 0, "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6,
    "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "dreizehn": 13, "vierzehn": 14,
    "fünfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19, "zwanzig": 20,
    "dreißig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60, "hundert": 100,
}

DATE_RE = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.(\d{2,4})?")
DATE_LONG_RE = re.compile(r"\b(\d{1,2})\.\s+(" + "|".join(MONTHS) + r")(?:\s+(\d{4}))?", re.I)
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?:\s*Uhr)?|\b(\d{1,2})\.(\d{2})\s*Uhr\b|\b(\d{1,2})\s*Uhr\b", re.I)
NUM_RE = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)(?![\w])")
LEGAL_RE = re.compile(r"§|\bVOB\b|\bBGB\b|\bAbs\.\s*\d", re.I)
CITE_RE = re.compile(r"\[(E-\d{2,3})\]")
ENTITY_RE = re.compile(
    r"((?:[A-ZÄÖÜ][\wäöüß.&-]*\s){0,3}(?:GmbH(?: & Co\. KG)?|KG|AG\b|SE\b|e\.K\.)"
    r"|(?:Ingenieurbüro|Architekturbüro|Büro|Firma)\s+[A-ZÄÖÜ][\wäöüß-]+"
    r"|(?:Herr|Frau)\s+(?:Dr\.\s|Dipl\.-Ing\.\s)?[A-ZÄÖÜ][\wäöüß-]+)")


def _numwords_to_digits(text: str) -> str:
    def repl(m):
        w = m.group(0).lower()
        if w.endswith("einhalb"):
            base = w[: -len("einhalb")]
            return f"{NUM_WORDS.get(base, 0)},5" if base in NUM_WORDS else m.group(0)
        return str(NUM_WORDS[w]) if w in NUM_WORDS else m.group(0)

    return re.sub(r"\b[a-zäöüß]+\b", repl, text, flags=re.I)


def _norm_num(s: str) -> str:
    s = s.replace(",", ".")
    try:
        f = float(s)
        return f"{f:g}"
    except ValueError:
        return s


def _dates_in(text: str, default_year: int | None = None) -> set[tuple[int, int, int | None]]:
    out = set()
    for d, m, y in DATE_RE.findall(text):
        if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            yy = int(y) + (2000 if y and len(y) == 2 else 0) if y else None
            out.add((int(d), int(m), yy))
    for d, mon, y in DATE_LONG_RE.findall(text):
        out.add((int(d), MONTHS[mon.lower()], int(y) if y else None))
    for y, m, d in ISO_RE.findall(text):
        out.add((int(d), int(m), int(y)))
    return out


def _times_in(text: str) -> set[int]:
    out = set()
    clean = _numwords_to_digits(text)
    for rx in (DATE_LONG_RE, ISO_RE):
        clean = rx.sub(" ", clean)
    clean = re.sub(r"\b\d{1,2}\.\d{1,2}\.(\d{2,4})?(?!\s*Uhr)", " ", clean)
    for h, m, h2, m2, h3 in TIME_RE.findall(clean):
        hh, mm = (h, m) if h else (h2, m2) if h2 else (h3, "0")
        if hh and int(hh) < 24 and int(mm) < 60:
            out.add(int(hh) * 60 + int(mm))
    if re.search(r"halb\s+zwei", text, re.I):
        out.add(13 * 60 + 30)
    return out


def _strip_dates_times(text: str) -> str:
    text = CITE_RE.sub(" ", text)
    for rx in (DATE_LONG_RE, DATE_RE, ISO_RE, TIME_RE):
        text = rx.sub(" ", text)
    return text


def _numbers_in(text: str) -> set[str]:
    return {_norm_num(n) for n in NUM_RE.findall(_strip_dates_times(_numwords_to_digits(text)))}


def known_entities() -> list[str]:
    b = settings.baseline()
    names = [b["company"]["name"]]
    for p in [settings.project_cfg(x["id"]) for x in b["projects"]]:
        c = p.get("client", {})
        names += [c.get("name", ""), c.get("representative", "")]
        names += [x["name"] for x in p.get("parties", [])]
        names += [x["name"] for x in p.get("crews", [])]
    return [n for n in names if n and n != "N. N."]


def _entities_in(text: str) -> set[str]:
    found = {m.strip() for m in ENTITY_RE.findall(text)}
    for n in known_entities():
        if n.lower() in text.lower():
            found.add(n)
        else:
            last = n.split()[-1]
            if len(last) > 3 and re.search(rf"\b{re.escape(last)}\b", text):
                found.add(last)
    return {f for f in found if len(f) > 2}


AI_PROMOTED = ("confirmed", "corroborated")


def is_ai_observation(d: dict) -> bool:
    return (d or {}).get("source") == "ai_vision"


def counts_as_evidence(d: dict) -> bool:
    """Foto, Audio, Mail … immer; KI-Beobachtung nur nach Bestätigung bzw. Stützung durch Sprache/Notiz."""
    if not d:
        return False
    if is_ai_observation(d):
        return (d.get("meta") or {}).get("status") in AI_PROMOTED
    return True


def _haystack(texts: Iterable[str]) -> dict[str, Any]:
    full = " \n ".join(t for t in texts if t)
    return {"text": full.lower(), "dates": _dates_in(full), "times": _times_in(full),
            "numbers": _numbers_in(full)}


def _date_ok(d: tuple[int, int, int | None], hay: dict) -> bool:
    return any(d[0] == x[0] and d[1] == x[1] and (d[2] is None or x[2] is None or d[2] == x[2])
               for x in hay["dates"])


def _ev_text(d: dict) -> str:
    """Belegtext inkl. Erfassungszeitpunkt (z. B. Mail-Eingang 12:15 Uhr am 20.11.2026)."""
    ts = ""
    if d.get("captured_at"):
        try:
            dt = datetime.fromisoformat(d["captured_at"])
            ts = f" erfasst am {dt:%d.%m.%Y} um {dt:%H:%M} Uhr"
        except ValueError:
            pass
    return f"{d.get('quote') or ''} {d.get('full_text') or ''} {d.get('title') or ''}{ts}"


def verify_sentences(sections: dict[str, list[dict]], evidence_map: dict[str, str],
                     evidence_docs: dict[str, dict]) -> list[VerificationIssue]:
    """sections: {"sachverhalt": [{"text","evidence":[E-01]}], ...}; evidence_map: E-01 → EV-0001."""
    all_hay = _haystack([_ev_text(d) for d in evidence_docs.values() if counts_as_evidence(d)])
    issues: list[VerificationIssue] = []
    n = 0

    def add(section, i, kind, value, status, found=None, msg=""):
        nonlocal n
        n += 1
        issues.append(VerificationIssue(issue_id=f"V{n:03d}", section=section, sentence=i, kind=kind, value=value,
                                        status=status, found_in=found, message=msg))

    for section, sentences in sections.items():
        for i, s in enumerate(sentences):
            text = s["text"]
            cites = list(dict.fromkeys(list(s.get("evidence", [])) + CITE_RE.findall(text)))
            valid = [c for c in cites if c in evidence_map]
            if not valid:
                add(section, i, "uncited", text[:60], "unverified", msg="Satz ohne gültigen Beleg")
            for c in cites:
                if c not in evidence_map:
                    add(section, i, "citation", c, "unverified", msg=f"Beleg {c} existiert nicht")
            if valid and not any(counts_as_evidence(evidence_docs.get(evidence_map[c], {})) for c in valid):
                ai = [c for c in valid if is_ai_observation(evidence_docs.get(evidence_map[c], {}))]
                add(section, i, "ai_only", ", ".join(ai) or text[:60],
                    "needs_confirmation" if ai else "unverified",
                    msg="Satz stützt sich nur auf eine KI-Beobachtung (kein Beleg) – bitte bestätigen"
                    if ai else "Zitierte Belege nicht vorhanden")
            if LEGAL_RE.search(text):
                add(section, i, "legal_ref", LEGAL_RE.search(text).group(0), "unverified",
                    msg="Normzitat im KI-Text – nur aus Vorlage zulässig")
            cited_docs = {c: evidence_docs.get(evidence_map[c], {}) for c in valid
                          if counts_as_evidence(evidence_docs.get(evidence_map[c], {}))}
            cited = {c: _haystack([_ev_text(d)]) for c, d in cited_docs.items()}

            def locate(pred) -> tuple[str, str | None]:
                for c, h in cited.items():
                    if pred(h):
                        return "verified", c
                if pred(all_hay):
                    return "verified", "andere Quelle"
                return "unverified", None

            for d in _dates_in(text):
                st, where = locate(lambda h, d=d: _date_ok(d, h))
                add(section, i, "date", f"{d[0]:02d}.{d[1]:02d}." + (str(d[2]) if d[2] else ""), st, where,
                    "" if st == "verified" else "Datum in keinem Beleg gefunden")
            for t in _times_in(text):
                st, where = locate(lambda h, t=t: t in h["times"])
                add(section, i, "time", f"{t // 60:02d}:{t % 60:02d}", st, where,
                    "" if st == "verified" else "Uhrzeit in keinem Beleg gefunden")
            for num in _numbers_in(text):
                st, where = locate(lambda h, num=num: num in h["numbers"])
                add(section, i, "number", num.replace(".", ","), st, where,
                    "" if st == "verified" else "Zahl in keinem Beleg gefunden")
            for ent in _entities_in(text):
                st, where = locate(lambda h, ent=ent: ent.lower() in h["text"])
                add(section, i, "entity", ent, st, where, "" if st == "verified" else "Name in keinem Beleg gefunden")
    return issues


def blocking(issues: list[dict] | list[VerificationIssue]) -> list:
    """Rot (unverified) und gelb (needs_confirmation) sperren die Freigabe, bis die Bauleitung bestätigt."""
    out = []
    for x in issues:
        d = x.model_dump() if hasattr(x, "model_dump") else x
        if d["status"] in ("unverified", "needs_confirmation"):
            out.append(d)
    return out
