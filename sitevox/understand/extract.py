"""Strukturierte Extraktion (Qwen3-4B-Instruct-2507): Text → Ereignisse, Leistungsmeldungen, Personal.

Läuft 1× deterministisch (temperature 0) + n Stichproben (temperature > 0) für die Konsistenz-Konfidenz.
Im Demo-Modus werden Fixtures abgespielt; für neue Freitexte greift eine Schlüsselwort-Heuristik,
damit die mobile Erfassung auch ohne GPU sichtbar Ergebnisse liefert.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any, Optional

from .. import llm, settings
from ..prompts import EXTRACT_PHOTO_CONTEXT, EXTRACT_USER, MINUTES_SYSTEM, extract_system
from ..schemas import Extraction, LLMEvent, LLMLogEntry, LLMProgress, LLMStaffing, LLMStaffingTotal, MinutesSummary

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------------- activity matching
def match_activity(name: str, acts: list[dict], threshold: float = 0.55) -> Optional[str]:
    n = name.lower()
    best, best_id = 0.0, None
    for a in acts:
        for cand in [a["name"]] + a.get("aliases", []):
            c = cand.lower()
            r = 1.0 if c in n or n in c else SequenceMatcher(None, n, c).ratio()
            if r > best:
                best, best_id = r, a["id"]
    return best_id if best >= threshold else None


# ----------------------------------------------------------------------------- heuristic fallback
KEYWORDS: list[tuple[str, str]] = [
    (r"\bpl(ä|ae)ne?\b.*\b(fehl|nicht|kommen|ausstehend)|freigabe fehlt|planlieferung|drawings?\b.*\b(missing|late|not)", "planlieferverzug"),
    (r"zus(ä|ae)tzlich|nicht im lv|zusatzleistung|extra beauftragt|additional work|not in the (boq|contract)", "additional_work"),
    (r"ge(ä|ae)ndert|(ä|ae)nderung|umplanung|anordnung des", "leistungsaenderung"),
    (r"(bagger|kran|pumpe|radlader|ger(ä|ae)t)\w*.*(defekt|kaputt|steht|ausgefallen|geplatzt|schaden)",
     "equipment_failure"),
    (r"(excavator|crane|pump|loader)\w*.*(broken|down|idle|failed|burst|damage)", "equipment_failure"),
    (r"krank|fehlen \w+ (mann|leute)|personal(mangel)?|zu wenig leute|sick|short of (staff|workers)", "worker_shortage"),
    (r"starkregen|sturm|frost|schnee|unwetter|hagel|heavy rain|storm|snow", "weather_interruption"),
    (r"(material|lieferung|beton)\w*.*(nicht geliefert|versp(ä|ae)t|fehlt|kommt nicht)", "material_delay"),
    (r"bedenken|planungsfehler|falsch geplant|statisch nicht", "design_error"),
    (r"mangel|riss|undicht|nacharbeit", "quality_defect"),
    (r"vorunternehmer|andere firma|fremdfirma|gewerk .* (blockiert|im weg)", "third_party_interference"),
]
GUESS = {"planlieferverzug": "AG", "additional_work": "AG", "leistungsaenderung": "AG", "design_error": "AG",
         "equipment_failure": "AN", "worker_shortage": "AN", "material_delay": "AN", "quality_defect": "AN",
         "weather_interruption": "neutral", "third_party_interference": "unklar"}
QTY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(m³|m3|kubik(?:meter)?|t\b|tonnen|m\b|meter|stück|stk)", re.I)
UNIT = {"m3": "m³", "kubik": "m³", "kubikmeter": "m³", "tonnen": "t", "meter": "m", "stück": "Stk", "stk": "Stk"}
TIME_RE = re.compile(r"\b(?:seit|ab|um|bis)?\s*(\d{1,2})(?:[:.](\d{2}))?\s*uhr\b|\b(\d{1,2}):(\d{2})\b", re.I)
# Verantwortungs-Hinweise aus der Antwort (nur Heuristik/Demo – im GPU-Modus füllt das LLM diese Felder)
ATTR_CUES: list[tuple[str, str, bool]] = [
    (r"vorleistung|vorunternehmer|vorgewerk|nicht (unsere|von uns)|fremde leistung|previous trade|not our", "own_work", False),
    (r"(unsere|eigene) leistung|von uns (betoniert|gebaut|hergestellt|verlegt)|our (own )?work", "own_work", True),
    (r"im auftrag de[sr] (bauherrn|ag|auftraggebers)|vom (bauherrn|ag) beauftragt|vorunternehmer|on behalf of the (client|owner)",
     "predecessor_by_owner", True),
    (r"unser(e)? (nach|sub)unternehmer|unsere? lieferant", "predecessor_by_owner", False),
    (r"(vom|des) (bauherrn|ag|auftraggebers) (beigestellt|geliefert)|bauherrenmaterial|beistellung", "owner_supplied_material", True),
]
# Fototyp → Ereignistyp, falls die Antwort selbst kein Schlüsselwort enthält (Heuristik)
SUBTYPE_EVENT = {"crack": "quality_defect", "surface_defect": "quality_defect", "damage": "quality_defect",
                 "standing_water": "weather_interruption", "material_storage": "third_party_interference",
                 "blocked_access": "third_party_interference", "equipment_idle": "equipment_failure"}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _attr_cues(text: str) -> dict[str, bool]:
    low, out = text.lower(), {}
    for pat, key, val in ATTR_CUES:
        if key not in out and re.search(pat, low):
            out[key] = val
    return out


# ----------------------------------------------------------------------------- Tagesbuch (normaler Ablauf)
EQUIPMENT_WORDS = ["minibagger", "bagger", "radlader", "kran", "turmdrehkran", "betonpumpe", "pumpe", "walze",
                   "rüttelplatte", "dumper", "teleskoplader", "lkw", "excavator", "crane", "loader", "pump"]
OK_RE = re.compile(r"in ordnung|alles (gut|ok)|\bok\b|dicht|hält|läuft( wieder)?\b|funktioniert|einsatzbereit|"
                   r"keine (probleme|auffälligkeiten)|all good|works fine|no issues", re.I)
FAIL_RE = re.compile(r"defekt|kaputt|ausgefallen|geplatzt|undicht|verliert öl|steht still|broken|leak", re.I)
NOT_USED_RE = re.compile(r"(heute )?nicht (gebraucht|eingesetzt|im einsatz)|abgestellt|not used", re.I)
IN_OP_RE = re.compile(r"im einsatz|gearbeitet|arbeitet|läuft seit|in betrieb|working|in operation", re.I)
DELIVERY_RE = re.compile(r"lieferung|geliefert|angeliefert|anlieferung|lkw mit|delivered|delivery", re.I)
EXPECT_RE = re.compile(r"kommt|kommen|erwartet|angekündigt|soll(en)? .*(kommen|geliefert)|morgen|übermorgen|"
                       r"expected|tomorrow|will arrive", re.I)
INSPECTION_RE = re.compile(r"abnahme|prüfstatiker|prüfingenieur|bewehrungsabnahme|kontrolle|geprüft|begehung|"
                           r"inspection|inspected", re.I)
VISIT_RE = re.compile(r"besuch|war (heute )?(da|vor ort|auf der baustelle)|kam vorbei|visit", re.I)
WEEKDAYS_DE = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
PARTY_RE = re.compile(r"(prüfstatiker|prüfingenieur|bauherr\w*|architekt\w*|bauleiter\w*|gutachter\w*|"
                      r"sigeko|ordnungsamt|berufsgenossenschaft|bg bau|statiker\w*)", re.I)
MATERIAL_RE = re.compile(r"(?:lieferung|anlieferung|lkw)\s+(?:mit|von|vom|für)?\s*(?:den|dem|der|die|das)?\s*"
                         r"([\wäöüß][\wäöüß\-/ ]{2,40}?)(?=\s+(?:ist|sind|kam|kommt|wurde|auf|heute|um|für|steht)\b|[,.]|$)",
                         re.I)


def _expected_date(sentence: str, day: Optional[str]) -> Optional[str]:
    if not day:
        return None
    from datetime import date as _d, timedelta

    d0, low = _d.fromisoformat(day), sentence.lower()
    if "übermorgen" in low:
        return (d0 + timedelta(days=2)).isoformat()
    if "morgen" in low or "tomorrow" in low:
        return (d0 + timedelta(days=1)).isoformat()
    for i, wd in enumerate(WEEKDAYS_DE):
        if re.search(rf"\b{wd}\b", low):
            ahead = (i - d0.weekday()) % 7 or 7
            return (d0 + timedelta(days=ahead)).isoformat()
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})?", sentence)
    if m:
        y = int(m.group(3) or d0.year)
        try:
            return _d(y, int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    return None


def _hhmm(s: str) -> Optional[str]:
    tm = TIME_RE.search(s)
    if not tm:
        return None
    h, m = (tm.group(1), tm.group(2)) if tm.group(1) else (tm.group(3), tm.group(4))
    return f"{int(h):02d}:{int(m or 0):02d}"


def log_heuristic(text: str, acts: list[dict], resources: Optional[list[str]] = None,
                  day: Optional[str] = None) -> list[LLMLogEntry]:
    """Normale Tagesbuch-Einträge per Schlüsselwort (Demo/Fallback). Gerät aus dem Satz oder dem Satz davor
    ("Bagger angeschaut … Mit der Maschine ist alles in Ordnung")."""
    out: list[LLMLogEntry] = []
    names = sorted({*(r.lower() for r in resources or []), *EQUIPMENT_WORDS}, key=len, reverse=True)
    last_res: Optional[str] = None
    seen_res: set[str] = set()
    for s in _sentences(text):
        low = s.lower()
        res = next((n for n in names if re.search(rf"\b{re.escape(n)}", low)), None)
        res_name = None
        if res:
            res_name = next((r for r in resources or [] if r.lower() == res), res.capitalize())
            last_res = res_name
        elif re.search(r"\b(maschine|gerät|machine)\b", low):
            res_name = last_res
        t = _hhmm(s)
        # Lieferung (angekommen oder angekündigt) – Verzug/Fehlmenge bleibt Ereignis (material_delay)
        if DELIVERY_RE.search(low) and not re.search(r"nicht geliefert|versp(ä|ae)t|fehlt|kommt nicht|ausgeblieben", low):
            expected = bool(EXPECT_RE.search(low)) and not re.search(r"angekommen|ist da|gekommen|abgeladen|geliefert", low)
            qm = QTY_RE.search(s)
            mm = MATERIAL_RE.search(s)
            unit = qm.group(2).lower() if qm else None
            supplied_by = "AG" if re.search(r"beigestellt|bauherrenmaterial|vom (bauherrn|ag)", low) else None
            note = re.search(r"lieferschein(?:-?nr\.?| nummer)?\s*([A-Z0-9\-/]{3,})", s, re.I)
            out.append(LLMLogEntry(kind="delivery", text=s, quote=s, time=None if expected else t,
                                   material=(mm.group(1).strip() if mm else None),
                                   quantity=float(qm.group(1).replace(",", ".")) if qm else None,
                                   unit=UNIT.get(unit, qm.group(2)) if qm else None, supplied_by=supplied_by,
                                   delivery_note_no=note.group(1) if note else None, arrived=not expected,
                                   expected_date=_expected_date(s, day) if expected else None,
                                   expected_time=t if expected else None))
            continue
        if INSPECTION_RE.search(low):
            pm = PARTY_RE.search(s)
            result = "ohne Beanstandung" if re.search(r"ohne (beanstandung|mängel)|in ordnung|abgenommen|freigegeben", low) else None
            act = match_activity(s, acts, 0.99)
            out.append(LLMLogEntry(kind="inspection", text=s, quote=s, time=t, party=pm.group(1) if pm else None,
                                   result=result, activity=next((a["name"] for a in acts if a["id"] == act), None)))
            continue
        if VISIT_RE.search(low):
            pm = PARTY_RE.search(s)
            out.append(LLMLogEntry(kind="visit", text=s, quote=s, time=t, party=pm.group(1) if pm else None))
            continue
        if res_name and not FAIL_RE.search(low):
            # geprüft + in Ordnung = verfügbar/im Einsatz (Schema kennt kein "checked_ok" mehr)
            state = ("not_used" if NOT_USED_RE.search(low) else "in_operation" if OK_RE.search(low)
                     else "in_operation" if IN_OP_RE.search(low) else None)
            if state:
                if res_name in seen_res:  # gleicher Befund in Folgesatz → an vorhandenen Eintrag anhängen
                    e = next(x for x in out if x.kind == "equipment_use" and x.resource == res_name)
                    e.quote, e.text = f"{e.quote} {s}", f"{e.text} {s}"
                    e.state = e.state or state
                    continue
                seen_res.add(res_name)
                out.append(LLMLogEntry(kind="equipment_use", text=s, quote=s, time=t, resource=res_name, state=state))
    return out


def heuristic(text: str, acts: list[dict], hint_subtypes: Optional[list[str]] = None,
              resources: Optional[list[str]] = None, day: Optional[str] = None) -> Extraction:
    events, progress, staffing = [], [], []
    staffing_total = None
    attrs = _attr_cues(text)
    for s in _sentences(text):
        low = s.lower()
        for pat, typ in KEYWORDS:
            if re.search(pat, low):
                tm = TIME_RE.search(s)
                t = None
                if tm:
                    h, m = (tm.group(1), tm.group(2)) if tm.group(1) else (tm.group(3), tm.group(4))
                    t = f"{int(h):02d}:{int(m or 0):02d}"
                act = match_activity(s, acts, 0.99)
                effects = []
                gm = re.search(r"\b(bagger|kran|betonpumpe|pumpe|radlader|excavator|crane|pump)\b", low)
                if typ == "equipment_failure" and gm:
                    effects.append({"resource": gm.group(1).capitalize(), "status": "idle", "start_time": t})
                events.append(LLMEvent(
                    type=typ, description=s, cause=s[:120], start_time=t, resource_effects=effects,
                    affected_activities=[next(a["name"] for a in acts if a["id"] == act)] if act else [],
                    responsible_party_guess=GUESS.get(typ, "unklar"),
                    responsible_rationale="Heuristik (Demo-Modus, Schlüsselwort)", quotes=[s], **attrs))
                break
        for m in QTY_RE.finditer(s):
            act = match_activity(s, acts, 0.99)
            if act:
                unit = m.group(2).lower()
                progress.append(LLMProgress(activity=next(a["name"] for a in acts if a["id"] == act),
                                            quantity=float(m.group(1).replace(",", ".")),
                                            unit=UNIT.get(unit, m.group(2)), quote=s))
        pm = re.search(r"(\d+)\s*(mann|leute|personen)", low)
        if pm and ("personal" in low or "kolonne" in low):
            staffing_total = LLMStaffingTotal(present_total=int(pm.group(1)), quote=s)
    # Foto-Antwort ohne Schlüsselwort ("Vorleistung von Firma X"): Ereignistyp aus der Beobachtung,
    # Zitat und Verantwortungs-Hinweise aber aus der Antwort.
    typ = next((SUBTYPE_EVENT[h] for h in hint_subtypes or [] if h in SUBTYPE_EVENT), None)
    if typ == "quality_defect" and events and all(e.type == "third_party_interference" for e in events):
        events[0].type = typ  # "Vorunternehmer" bei einem Riss-Foto = Mangel einer Vorleistung, keine Behinderung
        del events[1:]
    if typ and not events and text.strip():
        quote = _sentences(text)[0]
        events.append(LLMEvent(type=typ, description=text.strip()[:200], cause=text.strip()[:120], quotes=[quote],
                               responsible_party_guess=GUESS.get(typ, "unklar"),
                               responsible_rationale="Heuristik (Demo-Modus, Fotobefund + Antwort)", **attrs))
    logs = log_heuristic(text, acts, resources, day)
    # Ein Satz wird entweder Ereignis oder Tagesbuch-Eintrag, nicht beides
    ev_quotes = {q for e in events for q in e.quotes}
    logs = [l for l in logs if l.quote not in ev_quotes]
    return Extraction(summary=text[:200], events=events, progress=progress, staffing=staffing,
                      staffing_total=staffing_total, log_entries=logs)


# ----------------------------------------------------------------------------- API
def photo_context(question: str, analysis: dict) -> str:
    """Kontextblock für die Extraktion einer Foto-Antwort (KI-Beobachtungen ausdrücklich nicht zitierfähig)."""
    obs = analysis.get("observations") or []
    lines = "\n".join(f"- [{o['category']}/{o['subtype']}] {o['description']} (visuelle Sicherheit "
                      f"{float(o.get('visual_conf') or 0):.2f})" for o in obs) or "- keine"
    sc = analysis.get("scene") or {}
    scene = ", ".join(f"{k}: {v}" for k, v in (("Bauteil", sc.get("bauteil")), ("Stand", sc.get("stage")),
                                                ("Arbeit", sc.get("activity_guess"))) if v) or "–"
    if not question:  # Beschreibung kam mit dem Foto, ohne Rückfrage
        question = "(keine Rückfrage – freie Beschreibung des Poliers zum Foto)"
    return EXTRACT_PHOTO_CONTEXT.format(question=question, observations=lines, scene=scene)


def crew_names(pcfg: dict) -> list[str]:
    return [c["name"] for c in pcfg.get("crews", [])]


def equipment_names(pcfg: dict) -> list[str]:
    """Einsatzplan-Ressourcen ohne Kolonnen (baseline 'resources' enthält beides)."""
    crews = {n.lower() for n in crew_names(pcfg)}
    return [r["name"] for r in pcfg.get("resources", [])
            if r["name"].lower() not in crews and not r["name"].lower().startswith(("kolonne", "crew"))]


def extract(text: str, *, project_id: str, date: str, time: str, source: str, acts: list[dict],
            fixture_key: Optional[str] = None, context: str = "",
            hint_subtypes: Optional[list[str]] = None, out_lang: str = "de") -> dict[str, Any]:
    """Gibt {"main": Extraction, "samples": [Extraction, ...]} zurück.
    out_lang: Sprache der freien Textfelder (summary, description, …) = UI-Sprache; Zitate bleiben im Original.
    context: z. B. photo_context(...) – zusätzliche Einordnung, aus der NICHT zitiert werden darf."""
    pcfg = settings.project_cfg(project_id)
    cfg = settings.models()["llm"]["extractor"]
    msgs = [
        {"role": "system", "content": extract_system(out_lang)},
        {"role": "user", "content": EXTRACT_USER.format(
            project=pcfg["title"], date=date, time=time, source=source,
            activities=", ".join(a["name"] for a in acts),
            equipment=", ".join(equipment_names(pcfg)) or "–", crews=", ".join(crew_names(pcfg)) or "–",
            text=text, context=context)},
    ]
    client = llm.get("extractor")
    fx = (project_id, f"extract_{fixture_key}") if fixture_key else None
    fb = lambda: heuristic(text, acts, hint_subtypes,  # noqa: E731
                           [r["name"] for r in pcfg.get("resources", [])], date)
    try:
        main = client.structured(Extraction, msgs, n=1, temperature=cfg["temperature"], fixture=fx, fallback=fb)[0]
    except llm.LLMError as e:  # ungültiges JSON nach allen Retries → Heuristik statt Abbruch des Laufs
        log.warning("Extraktion fehlgeschlagen (%s) – Heuristik-Fallback", e)
        main = fb()
        return {"main": main, "samples": [main] * cfg["n_samples"]}
    try:
        samples = client.structured(Extraction, msgs, n=cfg["n_samples"], temperature=cfg["sample_temperature"],
                                    fixture=fx, fallback=fb)
    except llm.LLMError as e:
        log.warning("Konsistenz-Sampling fehlgeschlagen (%s) – nur Hauptlauf", e)
        samples = [main] * cfg["n_samples"]
    return {"main": main, "samples": samples}


def summarize_minutes(text: str, *, project_id: str, fixture_key: Optional[str] = None) -> MinutesSummary:
    msgs = [{"role": "system", "content": MINUTES_SYSTEM}, {"role": "user", "content": text}]

    def fallback() -> MinutesSummary:
        items = []
        for line in text.splitlines():
            m = re.search(r"(?:bis|Termin:?)\s*(\d{2})\.(\d{2})\.(\d{4})", line)
            if m and ("verantw" in line.lower() or "offen" in line.lower() or "bis" in line.lower()):
                items.append({"topic": line.strip("-* ").strip()[:140], "due": f"{m.group(3)}-{m.group(2)}-{m.group(1)}",
                              "quote": line.strip()})
        heads = [l.strip("# ").strip() for l in text.splitlines() if l.startswith("TOP") or l.startswith("## ")]
        return MinutesSummary(summary=heads[:6] or [text[:200]], open_items=items)

    fx = (project_id, f"minutes_{fixture_key}") if fixture_key else None
    return llm.get("drafter").structured(MinutesSummary, msgs, n=1, fixture=fx, fallback=fallback)[0]
