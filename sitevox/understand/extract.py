"""Strukturierte Extraktion (Qwen3-4B-Instruct-2507): Text → Ereignisse, Leistungsmeldungen, Personal.

Läuft 1× deterministisch (temperature 0) + n Stichproben (temperature > 0) für die Konsistenz-Konfidenz.
Im Demo-Modus werden Fixtures abgespielt; für neue Freitexte greift eine Schlüsselwort-Heuristik,
damit die mobile Erfassung auch ohne GPU sichtbar Ergebnisse liefert.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Optional

from .. import llm, settings
from ..prompts import EXTRACT_PHOTO_CONTEXT, EXTRACT_USER, MINUTES_SYSTEM, extract_system
from ..schemas import Extraction, LLMEvent, LLMProgress, LLMStaffing, MinutesSummary

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


def heuristic(text: str, acts: list[dict], hint_subtypes: Optional[list[str]] = None) -> Extraction:
    events, progress, staffing = [], [], []
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
            staffing.append(LLMStaffing(crew="Gesamt", present=int(pm.group(1)), quote=s))
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
    return Extraction(summary=text[:200], events=events, progress=progress, staffing=staffing)


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
            resources=", ".join(r["name"] for r in pcfg.get("resources", [])), text=text, context=context)},
    ]
    client = llm.get("extractor")
    fx = (project_id, f"extract_{fixture_key}") if fixture_key else None
    fb = lambda: heuristic(text, acts, hint_subtypes)  # noqa: E731
    main = client.structured(Extraction, msgs, n=1, temperature=cfg["temperature"], fixture=fx, fallback=fb)[0]
    samples = client.structured(Extraction, msgs, n=cfg["n_samples"], temperature=cfg["sample_temperature"],
                                fixture=fx, fallback=fb)
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
