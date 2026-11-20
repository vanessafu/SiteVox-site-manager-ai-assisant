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
from ..prompts import EXTRACT_SYSTEM, EXTRACT_USER, MINUTES_SYSTEM
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


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def heuristic(text: str, acts: list[dict]) -> Extraction:
    events, progress, staffing = [], [], []
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
                    responsible_rationale="Heuristik (Demo-Modus, Schlüsselwort)", quotes=[s]))
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
    return Extraction(summary=text[:200], events=events, progress=progress, staffing=staffing)


# ----------------------------------------------------------------------------- API
def extract(text: str, *, project_id: str, date: str, time: str, source: str, acts: list[dict],
            fixture_key: Optional[str] = None) -> dict[str, Any]:
    """Gibt {"main": Extraction, "samples": [Extraction, ...]} zurück."""
    pcfg = settings.project_cfg(project_id)
    cfg = settings.models()["llm"]["extractor"]
    msgs = [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {"role": "user", "content": EXTRACT_USER.format(
            project=pcfg["title"], date=date, time=time, source=source,
            activities=", ".join(a["name"] for a in acts),
            resources=", ".join(r["name"] for r in pcfg.get("resources", [])), text=text)},
    ]
    client = llm.get("extractor")
    fx = (project_id, f"extract_{fixture_key}") if fixture_key else None
    main = client.structured(Extraction, msgs, n=1, temperature=cfg["temperature"], fixture=fx,
                             fallback=lambda: heuristic(text, acts))[0]
    samples = client.structured(Extraction, msgs, n=cfg["n_samples"], temperature=cfg["sample_temperature"],
                                fixture=fx, fallback=lambda: heuristic(text, acts))
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
