"""Pydantic-Schemas: LLM-Ausgaben (streng validiert) und interne Datensätze."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Sphere = Literal["AG", "AN", "neutral"]
EventType = Literal[
    "material_delay",
    "equipment_failure",
    "weather_interruption",
    "worker_shortage",
    "third_party_interference",
    "design_error",
    "quality_defect",
    "additional_work",
    "planlieferverzug",
    "leistungsaenderung",
]
DocKind = Literal[
    "behinderungsanzeige",
    "mehrkostenankuendigung",
    "nachtragsankuendigung",
    "bedenkenanzeige",
    "bautagebuch",
    "interne_warnung",
]
EvidenceSource = Literal["audio", "photo", "email", "note", "document", "contract", "weather", "plan", "engine"]
ResourceStatus = Literal["work", "restricted", "idle", "planned_not_started"]

EVENT_TYPE_LABELS: dict[str, str] = {
    "material_delay": "Materiallieferverzug",
    "equipment_failure": "Geräteausfall",
    "weather_interruption": "Witterung",
    "worker_shortage": "Personalmangel",
    "third_party_interference": "Behinderung durch Dritte",
    "design_error": "Planungsfehler",
    "quality_defect": "Qualitätsmangel",
    "additional_work": "Zusätzliche Leistung",
    "planlieferverzug": "Planlieferverzug / fehlende Mitwirkung",
    "leistungsaenderung": "Leistungsänderung (AG-Anordnung)",
}
DOC_KIND_LABELS: dict[str, str] = {
    "behinderungsanzeige": "Behinderungsanzeige",
    "mehrkostenankuendigung": "Mehrkostenankündigung",
    "nachtragsankuendigung": "Nachtragsankündigung",
    "bedenkenanzeige": "Bedenkenanzeige",
    "bautagebuch": "Bautagebuch-Eintrag",
    "interne_warnung": "Interne Warnung",
}


# ---------------------------------------------------------------------------
# LLM-Ausgabe: Extraktion (Qwen3-4B). Das LLM liefert NUR Fakten + wörtliche Zitate.
# ---------------------------------------------------------------------------
class LLMResourceEffect(BaseModel):
    resource: str = Field(description="Gerät oder Kolonne, z. B. 'Bagger', 'Kolonne Müller'")
    status: ResourceStatus
    start_time: Optional[str] = Field(None, description="HH:MM")
    end_time: Optional[str] = Field(None, description="HH:MM oder null wenn offen")


class LLMEvent(BaseModel):
    type: EventType
    description: str = Field(description="Ein sachlicher Satz, was passiert ist")
    cause: str = Field(description="Ursache in Stichworten")
    start_time: Optional[str] = Field(None, description="HH:MM des Beginns, falls genannt")
    end_time: Optional[str] = None
    affected_activities: list[str] = Field(default_factory=list)
    resource_effects: list[LLMResourceEffect] = Field(default_factory=list)
    responsible_party_guess: Literal["AG", "AN", "neutral", "unklar"] = "unklar"
    responsible_rationale: str = ""
    impact_estimate_days: Optional[float] = None
    blocked_until: Optional[str] = Field(None, description="ISO-Datum, bis wann voraussichtlich blockiert")
    owner_supplied_material: Optional[bool] = None
    predecessor_by_owner: Optional[bool] = Field(None, description="Vorgewerk/Dritter im Auftrag des AG?")
    own_work: Optional[bool] = Field(None, description="Mangel an eigener Leistung?")
    work_started: Optional[bool] = Field(None, description="Zusatzleistung bereits begonnen?")
    ordered_by: Optional[str] = Field(None, description="Wer hat angeordnet (Name/Firma)")
    quotes: list[str] = Field(default_factory=list, description="Wörtliche Zitate aus der Eingabe als Beleg")


class LLMProgress(BaseModel):
    activity: str
    quantity: float
    unit: str
    quote: str


class LLMStaffing(BaseModel):
    crew: str
    present: int
    absent: Optional[int] = None
    reason: Optional[str] = None
    quote: str


class LLMOpenItem(BaseModel):
    topic: str
    responsible: Optional[str] = None
    due: Optional[str] = Field(None, description="ISO-Datum")
    quote: str


class Extraction(BaseModel):
    summary: str = ""
    events: list[LLMEvent] = Field(default_factory=list)
    progress: list[LLMProgress] = Field(default_factory=list)
    staffing: list[LLMStaffing] = Field(default_factory=list)
    open_items: list[LLMOpenItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM-Ausgabe: Entwurf (Qwen3-8B). Jeder Satz muss Beleg-IDs tragen.
# ---------------------------------------------------------------------------
class DraftSentence(BaseModel):
    text: str
    evidence: list[str] = Field(description="Beleg-IDs wie 'E-01'", min_length=1)


class DraftBody(BaseModel):
    sachverhalt: list[DraftSentence] = Field(min_length=1)
    auswirkungen: list[DraftSentence] = Field(min_length=1)


class SphereSuggestion(BaseModel):
    """LLM-Hilfsurteil zur Verantwortlichkeit – immer 'Vorschlag, menschliche Bestätigung nötig'."""

    party: Literal["AG", "AN", "neutral", "unklar"]
    rationale: str


class MinutesSummary(BaseModel):
    summary: list[str]
    open_items: list[LLMOpenItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Interne Datensätze
# ---------------------------------------------------------------------------
class Evidence(BaseModel):
    evidence_id: str
    project_id: str
    capture_id: Optional[str] = None
    source: EvidenceSource
    title: str = ""
    file: Optional[str] = None
    t_start: Optional[float] = None
    t_end: Optional[float] = None
    asr_score: Optional[float] = None
    quote: str = ""
    page: Optional[int] = None
    captured_at: Optional[str] = None
    full_text: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class ValueConf(BaseModel):
    value: Any = None
    confidence: float = 0.0


class RecommendedDocument(BaseModel):
    kind: DocKind
    basis: Optional[str] = None
    deadline: str = "—"
    reason: str = ""
    requires_letter: bool = False


class ResourceEffect(BaseModel):
    resource: str
    status: ResourceStatus
    start: str
    end: Optional[str] = None


class Event(BaseModel):
    event_id: str
    project_id: str
    date: str
    type: EventType
    sphere: Sphere
    sphere_rule: str = ""
    sphere_llm: Optional[SphereSuggestion] = None
    sphere_confirmed: bool = False
    start: str
    end: Optional[str] = None
    detected_at: str
    affected_activities: list[str] = Field(default_factory=list)
    activity_ids: list[str] = Field(default_factory=list)
    on_critical_path: bool = False
    impact_estimate_days: ValueConf = Field(default_factory=ValueConf)
    description: str = ""
    cause: str = ""
    evidence: list[str] = Field(default_factory=list)
    recommended_document: RecommendedDocument
    confidence: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    resource_effects: list[ResourceEffect] = Field(default_factory=list)
    blocked_until: Optional[str] = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    status: Literal["open", "draft", "released", "sent", "logged", "dismissed"] = "open"
    letter_id: Optional[str] = None


class LetterField(BaseModel):
    key: str
    label: str
    value: Any
    confidence: float
    evidence_ids: list[str] = Field(default_factory=list)
    importance: float = 0.5
    status: Literal["pending", "accepted", "edited", "rejected"] = "pending"
    note: str = ""


class VerificationIssue(BaseModel):
    issue_id: str
    section: str
    sentence: int
    kind: Literal["number", "date", "time", "entity", "citation", "legal_ref", "uncited"]
    value: str
    status: Literal["verified", "unverified", "confirmed"]
    found_in: Optional[str] = None
    message: str = ""


class Letter(BaseModel):
    letter_id: str
    project_id: str
    event_id: str
    kind: DocKind
    status: Literal["Entwurf", "Geprüft", "Versendet", "Verworfen"] = "Entwurf"
    fields: dict[str, LetterField]
    sections: dict[str, Any]
    evidence_map: dict[str, str]
    issues: list[VerificationIssue] = Field(default_factory=list)
    checklist: dict[str, bool] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    released_at: Optional[str] = None
    released_by: Optional[str] = None
    sent_at: Optional[str] = None
    exports: dict[str, str] = Field(default_factory=dict)
