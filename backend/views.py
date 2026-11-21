"""View-Modelle für das Frontend (Dashboard, Review-Editor). Keine Fachlogik – die liegt in sitevox/."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sitevox import confidence as conf
from sitevox import settings, store
from sitevox.drafting import composer
from sitevox.engine import deadlines, deviation, timeline
from sitevox.schemas import DOC_KIND_LABELS, EVENT_TYPE_LABELS

ACTIONABLE = ("open", "draft", "released")


def default_day(project_id: str) -> str:
    caps = store.captures(project_id)
    today = date.today().isoformat()
    days = sorted({c["date"] for c in caps})
    if today in days or not days:
        return today
    return days[-1]


def pending_letters(project_id: str) -> int:
    return sum(1 for e in store.events(project_id)
               if e["recommended_document"]["requires_letter"] and e["status"] in ACTIONABLE)


def projects() -> list[dict]:
    out = []
    for p in store.list_projects():
        out.append({**p, "badge": pending_letters(p["id"])})
    return out


def _bullet_color(ratio: Optional[float]) -> str:
    r = settings.rules()["bullet"]
    if ratio is None:
        return "none"
    return "red" if ratio < r["red_below"] else "yellow" if ratio < r["yellow_below"] else "green"


def event_card(e: dict) -> dict:
    letter = store.get("letters", e["letter_id"]) if e.get("letter_id") else None
    rd = e["recommended_document"]
    dl = deadlines.status(rd["kind"], e["detected_at"], work_started=e["attrs"].get("work_started"),
                          sent_at=(letter or {}).get("sent_at"))
    return {
        "event_id": e["event_id"], "type": e["type"], "label": EVENT_TYPE_LABELS[e["type"]],
        "description": e["description"], "cause": e["cause"], "sphere": e["sphere"],
        "sphere_rule": e.get("sphere_rule"), "sphere_llm": e.get("sphere_llm"),
        "sphere_confirmed": e.get("sphere_confirmed", False),
        "start": e["start"], "end": e.get("end"), "detected_at": e["detected_at"],
        "affected_activities": e["affected_activities"], "activity_ids": e["activity_ids"],
        "on_critical_path": e.get("on_critical_path"), "impact_estimate_days": e.get("impact_estimate_days"),
        "recommended_document": {**rd, "label": DOC_KIND_LABELS[rd["kind"]]},
        "confidence": e.get("confidence", {}), "warnings": e.get("warnings", []), "status": e["status"],
        "deadline": dl, "evidence": e["evidence"], "blocked_until": e.get("blocked_until"),
        "resource_effects": e.get("resource_effects", []), "date": e["date"], "attrs": {k: v for k, v in e["attrs"].items()
                                                             if k not in ("field_stats",)},
        "letter": {"letter_id": letter["letter_id"], "status": letter["status"],
                   "open_issues": len([i for i in letter["issues"] if i["status"] in ("unverified", "needs_confirmation")])}
        if letter else None,
    }


def dashboard(project_id: str, day: str) -> dict[str, Any]:
    d = date.fromisoformat(day)
    a = deviation.analyze(project_id, d)
    planned_today = {r["id"] for r in a["activities"] if r["today"]["soll"]}
    tl = timeline.day_timeline(project_id, day, planned_today)
    staff = store.staffing(project_id, day)
    total = next((s for s in staff if s["crew"] == "Gesamt"), None)
    present = total["present"] if total else sum(s["present"] for s in staff)
    planned = total["planned"] if total else sum(s["planned"] for s in staff)
    wx = store.weather(project_id, day) or {}
    evs = [e for e in store.events(project_id, day) if e["status"] != "dismissed"]
    cards = [event_card(e) for e in evs]
    extra = [c for c in cards if c["type"] in ("additional_work", "leistungsaenderung")]
    bullets = []
    for r in a["activities"]:
        if not r["today"]["soll"]:
            continue
        bullets.append({"id": r["id"], "name": r["name"], "unit": r["unit"], "soll": r["today"]["soll"],
                        "ist": r["today"]["ist"], "ratio": r["today"]["ratio"],
                        "color": _bullet_color(r["today"]["ratio"]), "events": r["events"],
                        "lv_pos": r["lv_pos"], "critical": r["critical"], "delay_days": r["delay_days"],
                        "forecast_finish": r["forecast_finish"], "cum": r["cum"], "qty": r["qty"]})
    order = {"critical": 0, "warn": 1, "info": 2, "ok": 3, "none": 4, "done": 5}
    cards.sort(key=lambda c: (not c["recommended_document"]["requires_letter"], order.get(c["deadline"]["level"], 9),
                              c["detected_at"]))
    return {
        "project": settings.project_cfg(project_id) | {"badge": pending_letters(project_id)},
        "date": day,
        "overview": {"kpis": a["kpis"], "window": a["window"], "today_idx": a["today_idx"],
                     "activities": a["activities"], "impact": a["impact"], "milestones": a["milestones"]},
        "today": {
            "kpis": {"day_target_ratio": a["kpis"]["day_target_ratio"],
                     "staff": {"present": present, "planned": planned, "detail": staff},
                     "weather": wx},
            "bullets": bullets, "extra_work": extra, "timeline": tl,
        },
        "actions": {"events": cards, "pending_letters": pending_letters(project_id)},
        "alerts": a["alerts"],
    }


def letter_view(letter: dict) -> dict[str, Any]:
    letter = composer.reverify(letter)
    ev = []
    for ref, eid in letter["evidence_map"].items():
        d = store.evidence(eid) or {}
        cap = store.get("captures", d["capture_id"]) if d.get("capture_id") else None
        ev.append({"ref": ref, **{k: d.get(k) for k in ("evidence_id", "source", "title", "file", "t_start", "t_end",
                                                         "asr_score", "quote", "page", "captured_at", "meta")},
                   "capture_title": cap["title"] if cap else None})
    fields = []
    for k, f in letter["fields"].items():
        fields.append({**f, "band": conf.band(f["confidence"]),
                       "evidence_refs": [r for r, eid in letter["evidence_map"].items() if eid in f["evidence_ids"]]})
    event = store.get("events", letter["event_id"])
    return {
        **{k: letter[k] for k in ("letter_id", "project_id", "event_id", "kind", "status", "checklist", "issues",
                                  "created_at", "updated_at", "released_at", "released_by", "sent_at", "exports")},
        "kind_label": DOC_KIND_LABELS[letter["kind"]],
        "rendered": letter["rendered"], "fields": fields, "evidence": ev,
        "queue": composer.review_queue(letter), "blockers": composer.release_blockers(letter),
        "checklist_labels": composer.CHECKLIST, "event": event_card(event) if event else None,
        "legal_refs": letter.get("legal_refs", []),
        "audit": store.audit_log(letter["letter_id"]),
    }
