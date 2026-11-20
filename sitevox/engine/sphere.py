"""Risikosphäre (AG | AN | neutral) und empfohlenes Schreiben – regelbasiert.

Grundsatz (§ 6 Abs. 2 VOB/B): Ausführungsfristen verlängern sich nur bei Umständen aus dem Risikobereich
des AG, Streik/Aussperrung oder höherer Gewalt / unabwendbaren Umständen. Normale Witterung zählt nicht.
→ Geräteausfall oder eigener Personalmangel = AN-Risiko: nur Bautagebuch, KEIN Schreiben an den AG.

Das LLM liefert nur eine Vermutung (responsible_party_guess + Begründung). Die Regel entscheidet; weicht
das LLM ab, sinkt die Konfidenz und es gibt einen Warnhinweis. Die UI zeigt stets
"Vorschlag – menschliche Bestätigung erforderlich".
"""
from __future__ import annotations

from typing import Any, Optional

from ..schemas import RecommendedDocument

# Matrix: Typ → (Standard-Sphäre, Begründung)
MATRIX: dict[str, dict[str, Any]] = {
    "material_delay": {"sphere": "AN", "why": "Beschaffungsrisiko liegt beim AN; bei AG-Beistellung AG"},
    "equipment_failure": {"sphere": "AN", "why": "Eigene Geräte – Risiko des AN"},
    "weather_interruption": {"sphere": "AN", "why": "Übliche Witterung ist einzukalkulieren (§ 6 Abs. 2 Nr. 2)"},
    "worker_shortage": {"sphere": "AN", "why": "Eigene Personaldisposition – Risiko des AN"},
    "third_party_interference": {"sphere": "AN", "why": "Nur Vorunternehmer des AG fallen in die AG-Sphäre"},
    "design_error": {"sphere": "AG", "why": "Planung wird vom AG geschuldet"},
    "quality_defect": {"sphere": "AN", "why": "Eigene Leistung AN; Vorleistung anderer Unternehmer → AG"},
    "additional_work": {"sphere": "AG", "why": "Vom AG geforderte, nicht vereinbarte Leistung"},
    "planlieferverzug": {"sphere": "AG", "why": "Planbeistellung ist Mitwirkungspflicht des AG"},
    "leistungsaenderung": {"sphere": "AG", "why": "Anordnung des AG"},
}

DOCS: dict[str, dict[str, Any]] = {
    "behinderungsanzeige": {"basis": "§ 6 Abs. 1 VOB/B", "deadline": "unverzüglich", "letter": True},
    "mehrkostenankuendigung": {"basis": "§ 2 Abs. 6 Nr. 1 VOB/B", "deadline": "vor Ausführung", "letter": True},
    "nachtragsankuendigung": {"basis": "§ 2 Abs. 5 VOB/B, § 650b BGB", "deadline": "möglichst vor Ausführung",
                              "letter": True},
    "bedenkenanzeige": {"basis": "§ 4 Abs. 3 VOB/B", "deadline": "unverzüglich, möglichst vor Beginn der Arbeiten",
                        "letter": True},
    "bautagebuch": {"basis": None, "deadline": "—", "letter": False},
    "interne_warnung": {"basis": None, "deadline": "—", "letter": False},
}


def rule_sphere(event_type: str, attrs: dict[str, Any], weather_exceptional: Optional[bool] = None) -> tuple[str, str]:
    m = MATRIX[event_type]
    sphere, why = m["sphere"], m["why"]
    if event_type == "material_delay" and attrs.get("owner_supplied_material"):
        sphere, why = "AG", "Vom AG beigestelltes Material"
    elif event_type == "weather_interruption":
        if weather_exceptional:
            sphere, why = "neutral", "DWD-Werte über den vereinbarten/üblichen Schwellen"
        else:
            sphere, why = "AN", "DWD-Werte im üblichen Rahmen – keine Behinderung (§ 6 Abs. 2 Nr. 2)"
    elif event_type == "third_party_interference" and attrs.get("predecessor_by_owner"):
        sphere, why = "AG", "Vorunternehmer im Auftrag des AG"
    elif event_type == "quality_defect" and attrs.get("own_work") is False:
        sphere, why = "AG", "Mangel einer Vorleistung"
    return sphere, why


def recommend(event_type: str, sphere: str, attrs: dict[str, Any], affects_schedule: bool) -> RecommendedDocument:
    kind, reason = "bautagebuch", "Nur Dokumentation im Bautagebuch"
    if event_type == "additional_work" and sphere == "AG":
        kind, reason = "mehrkostenankuendigung", "Zusätzliche Leistung: Mehrkosten vor Ausführung ankündigen"
    elif event_type == "leistungsaenderung" and sphere == "AG":
        kind, reason = "nachtragsankuendigung", "Geänderte Leistung: neuen Preis vereinbaren"
    elif event_type == "design_error":
        kind, reason = "bedenkenanzeige", "Technische Bedenken schriftlich mitteilen (ggf. zusätzlich Behinderung)"
    elif event_type == "quality_defect":
        kind, reason = ("bedenkenanzeige", "Bedenken gegen Vorleistung anderer Unternehmer") if sphere == "AG" \
            else ("interne_warnung", "Eigener Mangel: intern beseitigen (§ 4 Abs. 7)")
    elif event_type == "worker_shortage":
        kind, reason = "interne_warnung", "AN-Risiko; AG kann bei unzureichender Besetzung Abhilfe verlangen (§ 5 Abs. 3)"
    elif event_type == "equipment_failure":
        kind, reason = "bautagebuch", "AN-Risiko: Bautagebuch + interne Warnung, kein Schreiben an AG"
    elif sphere in ("AG", "neutral") and affects_schedule:
        kind, reason = "behinderungsanzeige", "Behinderung aus AG-Sphäre bzw. unabwendbarer Umstand"
    elif sphere in ("AG", "neutral"):
        kind, reason = "behinderungsanzeige", "Behinderung möglich – Auswirkung prüfen"
    d = DOCS[kind]
    return RecommendedDocument(kind=kind, basis=d["basis"], deadline=d["deadline"], reason=reason,
                               requires_letter=d["letter"])


def consistency_warnings(sphere: str, doc_kind: str, llm_guess: Optional[str]) -> list[str]:
    w = []
    if sphere == "AN" and doc_kind in ("behinderungsanzeige", "mehrkostenankuendigung", "nachtragsankuendigung"):
        w.append("Regelkonflikt: AN-Sphäre, aber Anzeige an AG vorgeschlagen")
    if llm_guess and llm_guess not in ("unklar", sphere):
        w.append(f"LLM-Einschätzung ({llm_guess}) weicht von Regel ({sphere}) ab – bitte prüfen")
    return w
