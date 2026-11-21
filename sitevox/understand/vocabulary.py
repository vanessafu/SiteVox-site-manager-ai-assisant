"""Projektvokabular für die Spracherkennung.

Whisper erkennt Fachbegriffe, Achsbezeichnungen und Eigennamen deutlich besser, wenn sie im
initial_prompt / als hotwords mitgegeben werden. Dieses Modul sammelt sie deterministisch aus
  · Projektunterlagen (Vertrag, LV, Planlieferliste, Protokolle – hochgeladene PDF/DOCX/Bilder),
  · im Foto lesbarem Text (OCR) und
  · den Projektstammdaten (Beteiligte, Kolonnen, Vorgänge),
plus manuell ergänzte Begriffe. Manuell entfernte Begriffe werden ausgeschlossen.

Whisper verarbeitet höchstens ~224 Prompt-Token (initial_prompt + hotwords zusammen); daher werden
die Begriffe nach Priorität gekürzt.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .. import settings, store

# Kategorien in Prioritätsreihenfolge (niedrigere Zahl = wichtiger)
CATEGORIES = {"manual": 0, "axis": 1, "company": 2, "spec": 3, "component": 4, "activity": 5}
CATEGORY_LABELS = {"manual": "Manuell", "axis": "Achsen / Bereiche", "company": "Firmen / Beteiligte",
                   "spec": "Materialien / Kennwerte", "component": "Bauteile / Leistungen", "activity": "Vorgänge / Kolonnen"}

AUDIO_PREFIX = "Sprachmemo: "
PROMPT_MAX_CHARS = 620    # Basis-Prompt + Projektbegriffe (~170 Token Deutsch)
HOTWORDS_MAX_CHARS = 180  # (~50 Token)

AXIS_RE = re.compile(r"\b(Achsen?|Bauteil|Bauabschnitt|BA|Haus|Treppenhaus|TH)\s+"
                     r"([A-Z]{1,2}\d{0,2}|\d{1,2})(?:\s*[/–-]\s*([A-Z]{1,2}\d{0,2}|\d{1,2}))?\b")
AXIS_GLUED_RE = re.compile(r"\b(BA|TH)(\d{1,2})\b")
COMPANY_RE = re.compile(
    # "AG" bewusst nicht als Rechtsform: im Bauvertrag steht AG für Auftraggeber
    # Trennzeichen [ \t] statt \s: Firmennamen nie über Zeilenumbrüche (OCR: "Lieferschein\nBetonwerk Huber GmbH")
    r"\b((?:[A-ZÄÖÜ][\wÄÖÜäöüß&.\-]*[ \t]){1,3}(?:GmbH(?:[ \t]*&[ \t]*Co\.?[ \t]*KG)?|KG|GbR|e\.[ \t]?K\.|mbB))"
    r"|\b((?:Ingenieurbüro|Architekturbüro|Planungsbüro|Vermessungsbüro|Kolonne|Firma|Fa\.)[ \t]+[A-ZÄÖÜ][\wäöüß\-]+)")
SPEC_RE = re.compile(
    r"\b(L?C\d{2}/\d{2}(?:\s*WU)?|X[CDFAM][A-Z]?\d|B500\s?[AB]?|DN\s?\d{2,4}|[QR]\d{3}\s?[AB]|"
    r"S\d{3}\s?(?:JR|J0|J2)?|HE[ABM]\s?\d{3}|IPE\s?\d{3}|WU-Beton|Ortbeton|Fertigteil\w*|Spannbeton)\b")
COMPONENT_SUFFIX = (r"platte|wand|wände|decke|stütze|stützen|träger|fundament\w*|bewehrung|schalung|beton|bohrung|"
                    r"bohrungen|schacht|treppe|balken|unterzug|dämmung|abdichtung|leitung|rohr|kanal|aushub|verbau|"
                    r"anker|pfahl|pfähle|estrich|mauerwerk|sohle|schicht|fuge|kran|pumpe|bagger|gerüst|stahl|matte|"
                    r"matten|korb|körbe|element|elemente|attika|brüstung|aussparung\w*|einrichtung|körper|bewehrungslage|"
                    r"durchbruch|durchbrüche|kernbohrung\w*|pläne|plan|anschluss|verguss|abschnitt")
COMPONENT_RE = re.compile(rf"\b([A-ZÄÖÜ][a-zäöüß]+(?:-?[a-zäöüß]+)*(?:{COMPONENT_SUFFIX}))\b")
NOT_TERMS = {"Plan", "Stahl", "Beton", "Lage", "Element", "Körper", "Schicht", "Abschnitt", "Anschluss", "Einrichtung",
             "Anlage", "Bauleitung", "Wohnanlage"}


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip(" .,;:-–")


def _scan(text: str, source: str, acc: dict[str, dict]) -> None:
    def add(term: str, cat: str) -> None:
        term = _norm(term)
        if len(term) < 3 or term in NOT_TERMS:
            return
        key = term.lower()
        e = acc.setdefault(key, {"term": term, "category": cat, "count": 0, "sources": []})
        if CATEGORIES[cat] < CATEGORIES[e["category"]]:
            e["category"] = cat
        e["count"] += 1
        if source not in e["sources"]:
            e["sources"].append(source)

    for m in AXIS_RE.finditer(text):
        head = "Achse" if m.group(1).startswith("Achse") else m.group(1)
        add(f"{head} {m.group(2)}" + (f"/{m.group(3)}" if m.group(3) else ""), "axis")
    for m in AXIS_GLUED_RE.finditer(text):
        add(f"{m.group(1)}{m.group(2)}", "axis")
    for m in COMPANY_RE.finditer(text):
        if m.group(1):  # "Firma Kranbau Sedlmeier GmbH" → "Kranbau Sedlmeier GmbH"
            add(re.sub(r"^(?:(?:Firma|Fa\.|Die|Der|Von|Bei|Mit|Und)\s+)+", "", m.group(1)), "company")
        else:
            add(re.sub(r"^(?:Firma|Fa\.)\s+", "", m.group(2)) if not m.group(2).startswith("Kolonne") else m.group(2), "company")
    for m in SPEC_RE.finditer(text):
        add(m.group(1), "spec")
    for m in COMPONENT_RE.finditer(text):
        add(m.group(1), "component")


def _overrides(project_id: str) -> dict:
    p = store.get("projects", project_id) or {}
    return p.get("asr_vocabulary") or {"added": [], "removed": []}


def _save_overrides(project_id: str, ov: dict) -> None:
    p = store.get("projects", project_id) or dict(settings.project_cfg(project_id))
    p["asr_vocabulary"] = ov
    store.save_project(p)


def collect(project_id: str) -> list[dict[str, Any]]:
    """Alle Begriffe mit Kategorie, Häufigkeit und Quellen – sortiert nach Priorität."""
    acc: dict[str, dict] = {}
    for d in store.documents(project_id):
        if d.get("collection") == "legal" or d.get("project_id") != project_id:
            continue
        text = "\n".join(p.get("text", "") for p in d.get("pages", []))
        text += "\n" + "\n".join(" | ".join(map(str, r)) for t in d.get("tables", []) for r in t.get("rows", []))
        _scan(text, d["title"], acc)
    for cap in store.captures(project_id):
        ocr_text = (cap.get("vision") or {}).get("ocr_text")
        if cap.get("kind") == "photo" and ocr_text:
            _scan(ocr_text, f"Foto-Text: {cap['title']}", acc)
        # Gesprochenes: Sprachmemos und gesprochene Antworten auf Foto-Rückfragen
        spoken = [(cap.get("transcript") or {}).get("text") if cap.get("kind") == "audio" else None,
                  ((cap.get("answer") or {}).get("transcript") or {}).get("text")]
        for s in filter(None, spoken):
            _scan(s, f"{AUDIO_PREFIX}{cap['title']}", acc)
    try:
        cfg = settings.project_cfg(project_id)
    except KeyError:
        cfg = {}
    names = [cfg.get("client", {}).get("name")] + [p.get("name") for p in cfg.get("parties", [])]
    for n in filter(None, names):
        acc.setdefault(n.lower(), {"term": n, "category": "company", "count": 0, "sources": []})
        acc[n.lower()]["sources"].append("Stammdaten")
        acc[n.lower()]["category"] = "company"
    for n in [c.get("name") for c in cfg.get("crews", [])] + [a.get("name") for a in store.activities(project_id)]:
        if not n:
            continue
        if n.lower() not in acc:
            acc[n.lower()] = {"term": n, "category": "activity", "count": 1, "sources": ["Stammdaten"]}
        elif "Stammdaten" not in acc[n.lower()]["sources"]:
            acc[n.lower()]["sources"].append("Stammdaten")

    ov = _overrides(project_id)
    removed = {t.lower() for t in ov.get("removed", [])}
    for t in ov.get("added", []):
        acc[t.lower()] = {"term": t, "category": "manual", "count": 0, "sources": ["manuell"]}
    terms = [e for k, e in acc.items() if k not in removed]
    for e in terms:
        e["from_audio"] = any(s.startswith(AUDIO_PREFIX) for s in e["sources"])
        # Nur aus Audio: könnte selbst ein Erkennungsfehler sein → nachrangig (keine Fehler-Rückkopplung)
        e["audio_only"] = e["from_audio"] and all(s.startswith(AUDIO_PREFIX) for s in e["sources"])
    terms.sort(key=lambda e: (e["audio_only"], CATEGORIES[e["category"]], -len(e["sources"]), -e["count"], e["term"]))
    return terms


def _fit(items: list[str], limit: int, sep: str = ", ") -> list[str]:
    out, n = [], 0
    for t in items:
        if n + len(t) + len(sep) > limit:
            continue
        out.append(t)
        n += len(t) + len(sep)
    return out


def for_asr(project_id: str | None) -> dict[str, list[str]]:
    """Sprachunabhängige Projektbegriffe für die Spracherkennung, nach Priorität (JSON-serialisierbar,
    wird bei asr.backend = "remote" mit dem Audio an den GPU-Knoten geschickt)."""
    if not project_id:
        return {"terms": [], "hot": []}
    terms = collect(project_id)
    return {"terms": [e["term"] for e in terms],
            "hot": [e["term"] for e in terms if CATEGORIES[e["category"]] <= CATEGORIES["spec"] and not e["audio_only"]]}


def compose(base: str | None, v: dict | None) -> dict[str, Any]:
    """initial_prompt + hotwords: Basis-Prompt (je erkannter Sprache) + Projektbegriffe, auf Whispers
    Prompt-Grenze gekürzt. Fachbegriffe/Eigennamen bleiben deutsch – so werden sie auch in TR/PL/EN-Aufnahmen erkannt."""
    v = v or {"terms": [], "hot": []}
    base = re.sub(r"\s+", " ", base or "").strip()
    base_l = base.lower()
    fresh = [t for t in v.get("terms", []) if t.lower() not in base_l]
    used = _fit(fresh, max(0, PROMPT_MAX_CHARS - len(base) - 2))
    prompt = (base.rstrip(".") + ", " + ", ".join(used) + ".") if used and base else (", ".join(used) or base)
    base_hot = list(settings.models()["asr"].get("hotwords", []))
    hot = _fit(list(dict.fromkeys(base_hot + list(v.get("hot", [])))), HOTWORDS_MAX_CHARS, " ")
    return {"initial_prompt": prompt or None, "hotwords": hot, "used": used}


def asr_prompt(project_id: str | None, base: str | None = None) -> dict[str, Any]:
    """Vorschau/Gesamtsicht: wie compose(), plus Begriffsliste mit in_prompt-Markierung (Basis: deutscher Prompt)."""
    if base is None:
        base = settings.models()["asr"].get("initial_prompt") or ""
    terms = collect(project_id) if project_id else []
    v = {"terms": [e["term"] for e in terms],
         "hot": [e["term"] for e in terms if CATEGORIES[e["category"]] <= CATEGORIES["spec"] and not e["audio_only"]]}
    p = compose(base, v)
    base_l = re.sub(r"\s+", " ", base).lower()
    in_prompt = {t.lower() for t in p["used"]}
    for e in terms:
        e["in_prompt"] = e["term"].lower() in in_prompt or e["term"].lower() in base_l
    return {"initial_prompt": p["initial_prompt"], "hotwords": p["hotwords"], "terms": terms, "used": len(p["used"])}


def add_term(project_id: str, term: str, actor: str) -> dict:
    term = _norm(term)
    if not term:
        raise ValueError("leerer Begriff")
    ov = _overrides(project_id)
    ov["removed"] = [t for t in ov.get("removed", []) if t.lower() != term.lower()]
    if term.lower() not in {t.lower() for t in ov.get("added", [])}:
        ov.setdefault("added", []).append(term)
    _save_overrides(project_id, ov)
    store.audit(actor, "project", project_id, "asr_term_add", after=term)
    return ov


def remove_term(project_id: str, term: str, actor: str) -> dict:
    ov = _overrides(project_id)
    ov["added"] = [t for t in ov.get("added", []) if t.lower() != term.lower()]
    if term.lower() not in {t.lower() for t in ov.get("removed", [])}:
        ov.setdefault("removed", []).append(term)
    _save_overrides(project_id, ov)
    store.audit(actor, "project", project_id, "asr_term_remove", before=term)
    return ov


def restore_term(project_id: str, term: str, actor: str) -> dict:
    ov = _overrides(project_id)
    ov["removed"] = [t for t in ov.get("removed", []) if t.lower() != term.lower()]
    _save_overrides(project_id, ov)
    store.audit(actor, "project", project_id, "asr_term_restore", after=term)
    return ov


def summary(project_id: str) -> dict[str, Any]:
    p = asr_prompt(project_id)
    by_cat: dict[str, list] = defaultdict(list)
    for e in p["terms"]:
        by_cat[e["category"]].append(e)
    return {
        "initial_prompt": p["initial_prompt"], "hotwords": p["hotwords"], "used": p["used"],
        "total": len(p["terms"]), "prompt_max_chars": PROMPT_MAX_CHARS,
        "from_audio": sum(1 for e in p["terms"] if e["from_audio"]),
        "audio_only": sum(1 for e in p["terms"] if e["audio_only"]),
        "groups": [{"category": k, "label": CATEGORY_LABELS[k], "terms": by_cat[k]} for k in CATEGORIES if by_cat.get(k)],
        "removed": _overrides(project_id).get("removed", []),
        "sources": dict(Counter(s for e in p["terms"] for s in e["sources"])),
    }
