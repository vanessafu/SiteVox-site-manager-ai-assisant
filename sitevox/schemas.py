"""Pydantic-Schemas: LLM-Ausgaben (streng validiert) und interne Datensätze."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
# "ai_vision" = KI-Beobachtung aus einem Foto (Qwen-VL). Ausdrücklich KEIN Beleg, nur Hinweis – zählt erst als
# Beleg, wenn die Bauleitung sie bestätigt oder die Sprach-/Textantwort sie stützt (meta.status, siehe verify.py).
EvidenceSource = Literal["audio", "photo", "email", "note", "document", "contract", "weather", "plan", "engine",
                         "ai_vision"]
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
EVENT_TYPE_LABELS_EN: dict[str, str] = {
    "material_delay": "Delay in material delivery",
    "equipment_failure": "Equipment failure",
    "weather_interruption": "Weather",
    "worker_shortage": "Labour shortage",
    "third_party_interference": "Obstruction by third parties",
    "design_error": "Design error",
    "quality_defect": "Quality defect",
    "additional_work": "Additional work",
    "planlieferverzug": "Late delivery of drawings / lack of cooperation",
    "leistungsaenderung": "Change of work (client instruction)",
}
DOC_KIND_LABELS_EN: dict[str, str] = {
    "behinderungsanzeige": "Notice of obstruction",
    "mehrkostenankuendigung": "Notice of additional costs",
    "nachtragsankuendigung": "Notice of change (modified work)",
    "bedenkenanzeige": "Notice of concerns",
    "bautagebuch": "Site diary entry",
    "interne_warnung": "Internal warning",
}


def labels(lang: str = "de") -> tuple[dict[str, str], dict[str, str]]:
    """(Ereignistyp-, Dokumentart-Labels) in der Ausgabesprache."""
    return (EVENT_TYPE_LABELS_EN, DOC_KIND_LABELS_EN) if lang == "en" else (EVENT_TYPE_LABELS, DOC_KIND_LABELS)


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
    """Ausgeführte Menge eines Vorgangs. Einzige Stelle für Mengen (work_done im Tagebuch hat keine Mengen)."""
    activity: str = Field(description="Vorgang, möglichst Name aus 'Bekannte Vorgänge'")
    quantity: float
    unit: str = Field(description="z. B. m³, t, m, m², Stk")
    quote: str = Field(description="Wörtliches Zitat NUR des Teils mit dieser Menge")


class LLMStaffing(BaseModel):
    """Kopfzahl einer genannten Kolonne. crew nur, wenn die Kolonne in der Eingabe genannt wird – nie raten."""
    crew: Optional[str] = Field(None, description="Kolonne wie genannt (z. B. 'Kolonne Müller'), sonst null")
    present: int
    absent: Optional[int] = None
    reason: Optional[str] = None
    quote: str


class LLMStaffingTotal(BaseModel):
    """Gesamtzahl Personal ohne Kolonnenzuordnung ("alle 16 Mann da"). Aufteilung auf Kolonnen entscheidet der
    Bauleiter im Dashboard."""
    present_total: int = Field(description="Gesamtzahl anwesender Personen inkl. Aushilfen")
    additional: Optional[int] = Field(None, description="davon zusätzlich/aushilfsweise (z. B. '+2 von Pasing')")
    note: Optional[str] = Field(None, description="Herkunft der Aushilfen o. Ä.")
    quote: str


class LLMOpenItem(BaseModel):
    topic: str
    responsible: Optional[str] = None
    due: Optional[str] = Field(None, description="ISO-Datum")
    quote: str


LogKind = Literal["delivery", "equipment_use", "inspection", "visit", "work_done"]
EquipmentState = Literal["in_operation", "idle", "restricted", "under_inspection", "not_used"]
LOG_KIND_LABELS: dict[str, str] = {"delivery": "Lieferung", "equipment_use": "Geräteeinsatz", "inspection": "Prüfung",
                                   "visit": "Besuch", "work_done": "Erledigte Arbeit"}
EQUIPMENT_STATE_LABELS: dict[str, str] = {"in_operation": "im Einsatz", "idle": "Stillstand",
                                          "restricted": "eingeschränkt", "under_inspection": "in Prüfung/Wartung",
                                          "not_used": "nicht eingesetzt",
                                          "checked_ok": "geprüft, in Ordnung"}  # Altdaten vor Schema-Änderung


class LLMLogEntry(BaseModel):
    """Tagesbuch-Eintrag ohne Störungscharakter (normaler Ablauf) – geht nur in den Bautagesbericht,
    nicht durch das Risikosphären-Regelwerk. Felder je Art; was nicht genannt wird, bleibt null."""
    kind: LogKind
    text: str = Field(description="Ein sachlicher Satz, was festgehalten wird")
    time: Optional[str] = Field(None, description="HH:MM, falls genannt")
    quote: str = Field(description="Wörtliches Zitat aus der Eingabe")
    # delivery
    material: Optional[str] = Field(None, description="Lieferung: was (z. B. 'Betonstahl B500B', 'Transportbeton C30/37')")
    quantity: Optional[float] = None
    unit: Optional[str] = None
    supplier: Optional[str] = Field(None, description="Lieferant/Firma")
    supplied_by: Optional[Literal["AN", "AG"]] = Field(None, description="AG = vom Bauherrn beigestellt")
    delivery_note_no: Optional[str] = Field(None, description="Lieferschein-Nr., falls genannt")
    arrived: Optional[bool] = Field(None, description="true = heute angekommen; false = nur angekündigt/erwartet")
    expected_date: Optional[str] = Field(None, description="ISO-Datum einer angekündigten Lieferung")
    expected_time: Optional[str] = Field(None, description="HH:MM der angekündigten/geplanten Anlieferung")
    # equipment_use
    resource: Optional[str] = Field(None, description="Gerät aus 'Bekannte Geräte' (nie eine Kolonne/ein Material)")
    state: Optional[EquipmentState] = None
    start_time: Optional[str] = Field(None, description="HH:MM Einsatzbeginn")
    end_time: Optional[str] = Field(None, description="HH:MM Einsatzende")
    # inspection / visit / work_done
    party: Optional[str] = Field(None, description="Prüfer/Besucher/Firma, z. B. 'Prüfstatiker', 'Bauherr'")
    result: Optional[str] = Field(None, description="Ergebnis einer Prüfung/Abnahme, z. B. 'ohne Beanstandung'")
    activity: Optional[str] = Field(None, description="Betroffener Vorgang, falls erkennbar")
    # work_done hat bewusst KEINE Menge: Mengen gehören immer in Extraction.progress


_EXTRACTION_FIELDS = ["summary", "events", "progress", "staffing", "staffing_total", "log_entries", "open_items"]


class Extraction(BaseModel):
    """Alle Felder sind im JSON-Schema PFLICHT (guided decoding muss jedes Feld ausgeben, leer = [] bzw. null);
    Python-seitig bleiben Defaults, damit Heuristik und ältere Demo-Fixtures weiter validieren."""
    model_config = ConfigDict(json_schema_extra={"required": _EXTRACTION_FIELDS})

    summary: str = ""
    events: list[LLMEvent] = Field(default_factory=list)
    progress: list[LLMProgress] = Field(default_factory=list)
    staffing: list[LLMStaffing] = Field(default_factory=list)
    staffing_total: Optional[LLMStaffingTotal] = None
    log_entries: list[LLMLogEntry] = Field(default_factory=list)
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
# VLM-Ausgabe: Fotoanalyse (Qwen3-VL). Das VLM sagt NUR, was zu sehen ist – nie wer es verursacht hat.
# Ursache/Verantwortliche/Mengen kommen aus der Sprach-/Textantwort, Sphäre und Schreiben aus dem Regelwerk.
# Wertebereiche werden per Validator geklemmt statt per JSON-Schema-Grenzen (guided decoding bleibt robust).
# ---------------------------------------------------------------------------
ObservationCategory = Literal["obstruction", "defect", "progress", "safety"]
ObservationSubtype = Literal[
    "blocked_access", "standing_water", "material_storage", "equipment_idle",  # obstruction
    "crack", "surface_defect", "damage",                                       # defect
    "stage_change",                                                            # progress
    "safety_hazard",                                                           # safety
    "other",
]
OBSERVATION_LABELS: dict[str, str] = {
    "blocked_access": "Zugang/Zufahrt blockiert", "standing_water": "stehendes Wasser",
    "material_storage": "Material auf der Arbeitsfläche", "equipment_idle": "Gerät steht still",
    "crack": "Riss", "surface_defect": "Oberflächenfehler", "damage": "Beschädigung",
    "stage_change": "Bauzustand / Fortschritt", "safety_hazard": "Sicherheitsmangel", "other": "Sonstiges",
}


class PhotoScene(BaseModel):
    bauteil: Optional[str] = Field(None, description="Sichtbares Bauteil, z. B. 'Bodenplatte', 'Wand EG'")
    stage: Optional[str] = Field(None, description="Bauzustand, z. B. 'untere Bewehrungslage verlegt'")
    activity_guess: Optional[str] = Field(None, description="Vermutlich laufende Arbeit, z. B. 'Bewehrung'")


class PhotoObservation(BaseModel):
    category: ObservationCategory
    subtype: ObservationSubtype
    description: str = Field(description="Ein sachlicher Satz, was zu sehen ist – ohne Ursache, ohne Schuld")
    bbox: Optional[list[int]] = Field(None, description="[x1, y1, x2, y2], relativ 0–1000")
    severity: Literal["low", "medium", "high"] = "medium"
    visual_conf: float = Field(0.5, description="Sicherheit der visuellen Erkennung 0–1")

    @field_validator("visual_conf", mode="before")
    @classmethod
    def _clamp_conf(cls, v: Any) -> float:
        try:
            return min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            return 0.5

    @field_validator("bbox", mode="before")
    @classmethod
    def _norm_bbox(cls, v: Any) -> Optional[list[int]]:
        """Ungültige Boxen verwerfen statt die ganze Analyse abzulehnen (Box ist optional)."""
        if not isinstance(v, (list, tuple)) or len(v) != 4:
            return None
        try:
            x1, y1, x2, y2 = (min(1000, max(0, int(round(float(c))))) for c in v)
        except (TypeError, ValueError):
            return None
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        return [x1, y1, x2, y2] if x2 - x1 >= 10 and y2 - y1 >= 10 else None


class PhotoAnalysis(BaseModel):
    summary: str = Field("", description="2–3 sachliche Sätze für das Bautagebuch (was ist zu sehen)")
    scene: PhotoScene = Field(default_factory=PhotoScene)
    observations: list[PhotoObservation] = Field(default_factory=list)
    followup_question: str = Field("Was ist hier passiert?", description="Eine kurze Rückfrage an den Polier")

    @field_validator("observations", mode="after")
    @classmethod
    def _limit(cls, v: list[PhotoObservation]) -> list[PhotoObservation]:
        return v[:6]


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
    kind: Literal["number", "date", "time", "entity", "citation", "legal_ref", "uncited", "ai_only"]
    value: str
    # needs_confirmation (gelb): Satz stützt sich nur auf KI-Beobachtungen – Freigabe erst nach Bestätigung
    status: Literal["verified", "unverified", "needs_confirmation", "confirmed"]
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
