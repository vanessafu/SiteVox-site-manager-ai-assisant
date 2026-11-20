"""Fristen-Ampel: Zeit seit Feststellung, Status je Schreibenart.

- Behinderungsanzeige: "unverzüglich schriftlich" (§ 6 Abs. 1) – Voraussetzung für Fristverlängerung
  (§ 6 Abs. 2) und Entschädigung/Schadensersatz (§ 6 Abs. 6).
- Mehrkostenankündigung (§ 2 Abs. 6 Nr. 1 S. 2): VOR Beginn der Ausführung. Wurde schon begonnen → kritisch.
- Nachtrag bei Leistungsänderung (§ 2 Abs. 5): keine Ankündigungspflicht, aber Vereinbarung soll vor
  Ausführung getroffen werden → "möglichst früh".
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from .. import settings


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def status(kind: str, detected_at: str, now: Optional[datetime] = None, work_started: Optional[bool] = None,
           sent_at: Optional[str] = None) -> dict[str, Any]:
    r = settings.rules()["deadlines"]
    det = _parse(detected_at)
    now = now or datetime.now(det.tzinfo)
    hours = max(0.0, (now - det).total_seconds() / 3600)
    out: dict[str, Any] = {"detected_at": detected_at, "elapsed_hours": round(hours, 1), "level": "ok", "label": ""}
    if sent_at:
        out.update(level="done", label="versendet")
        return out
    if kind == "behinderungsanzeige":
        # "unverzüglich" = ohne schuldhaftes Zögern → von Anfang an dringlich, nach warn_after_h kritisch
        level = "critical" if hours >= r["warn_after_h"] else "warn"
        out.update(level=level, label="unverzüglich schriftlich anzeigen")
    elif kind == "mehrkostenankuendigung":
        if work_started:
            out.update(level="critical", label="Ausführung bereits begonnen – Ankündigung verspätet?")
        else:
            out.update(level="warn", label="vor Ausführungsbeginn ankündigen")
    elif kind == "nachtragsankuendigung":
        out.update(level="info", label="möglichst vor Ausführung vereinbaren")
    elif kind == "bedenkenanzeige":
        out.update(level="warn" if hours < r["critical_after_h"] else "critical",
                   label="unverzüglich, möglichst vor Beginn der Arbeiten")
    else:
        out.update(level="none", label="keine Frist")
    return out
