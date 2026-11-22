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
    """Berichtstag des Dashboards = heute (Systemuhr des Servers). Frühere Tage stehen im Verlauf.
    Für Vorführungen lässt sich der Tag mit SITEVOX_TODAY=JJJJ-MM-TT festhalten (z. B. Demo-Tag 2026-11-20)."""
    import os

    from sitevox import settings as _settings

    return _settings.today() or date.today().isoformat()


def pending_letters(project_id: str) -> int:
    return sum(1 for e in store.events(project_id)
               if e["recommended_document"]["requires_letter"] and e["status"] in ACTIONABLE)


def projects() -> list[dict]:
    out = []
    for p in store.list_projects():
        out.append({**p, "badge": pending_letters(p["id"])})
    return out


def report_days(project_id: str) -> list[dict]:
    """Verlauf: Berichtstage (neueste zuerst) mit Erfassungen, Ereignissen und Wetter."""
    today = date.today().isoformat()
    out = []
    for d in store.report_days(project_id):
        if d > today:
            continue
        caps = store.captures(project_id, d)
        evs = [e for e in store.events(project_id, d) if e["status"] != "dismissed"]
        wx = store.weather(project_id, d) or {}
        logs = store.log_entries(project_id, d, "delivery")
        arrived = [l for l in logs if l.get("arrived") is not False]
        due = [l for l in store.log_entries(project_id, kind="delivery")
               if l.get("arrived") is False and l.get("expected_date") == d]
        out.append({"date": d, "captures": len(caps), "events": len(evs), "deliveries": len(arrived),
                    "delivery_materials": [l.get("material") or "?" for l in arrived],
                    "deliveries_open": max(len(due) - len(arrived), 0),
                    "open_letters": sum(1 for e in evs if e["recommended_document"]["requires_letter"]
                                        and e["status"] in ACTIONABLE),
                    "weather": (wx.get("summary") or {}).get("condition"),
                    "temp_max": (wx.get("summary") or {}).get("temp_max"), "photos": sum(1 for c in caps if c["kind"] == "photo")})
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
    # offene fristgebundene Vorgänge früherer Tage bleiben im Handlungsbedarf, bis sie erledigt sind
    carried = [e for e in store.events(project_id) if e["date"] < day and e["status"] in ACTIONABLE
               and e["recommended_document"]["requires_letter"]]
    cards = [event_card(e) for e in evs] + [{**event_card(e), "carried_from": e["date"]} for e in carried]
    extra = [c for c in cards if c["type"] in ("additional_work", "leistungsaenderung") and not c.get("carried_from")]
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
            "kpis": {"day_target_ratio": a["kpis"].get("day_target_ratio"),
                     "staff": {"present": present, "planned": planned, "detail": staff},
                     "weather": wx},
            "bullets": bullets, "extra_work": extra, "timeline": tl,
        },
        "actions": {"events": cards, "pending_letters": pending_letters(project_id)},
        "alerts": a["alerts"],
    }


def letter_view(letter: dict) -> dict[str, Any]:
    letter = composer.reverify(composer.ensure_recipient_email(letter))
    ev = []
    for ref, eid in letter["evidence_map"].items():
        d = store.evidence(eid) or {}
        cap = store.get("captures", d["capture_id"]) if d.get("capture_id") else None
        ev.append({"ref": ref, **{k: d.get(k) for k in ("evidence_id", "source", "title", "file", "t_start", "t_end",
                                                         "asr_score", "quote", "page", "captured_at", "meta")},
                   "capture_title": cap["title"] if cap else None, "source_key": source_key(d) if d else ref})
    fields = []
    for k, f in letter["fields"].items():
        fields.append({**f, "band": conf.band(f["confidence"]),
                       "evidence_refs": [r for r, eid in letter["evidence_map"].items() if eid in f["evidence_ids"]]})
    event = store.get("events", letter["event_id"])
    return {
        **{k: letter[k] for k in ("letter_id", "project_id", "event_id", "kind", "status", "checklist", "issues",
                                  "created_at", "updated_at", "released_at", "released_by", "sent_at", "exports")},
        "sent_method": letter.get("sent_method"), "sent_email": letter.get("sent_email"),
        "original": letter.get("original"),
        "kind_label": DOC_KIND_LABELS[letter["kind"]],
        "rendered": letter["rendered"], "fields": fields, "evidence": ev,
        "queue": composer.review_queue(letter), "blockers": composer.release_blockers(letter),
        "checklist_labels": composer.CHECKLIST, "event": event_card(event) if event else None,
        "legal_refs": letter.get("legal_refs", []),
        "audit": store.audit_log(letter["letter_id"]),
    }


# ============================================================================ Belege nach Quelle gruppiert
def source_key(e: dict) -> str:
    """Eine Quelle = eine Aufnahme/Datei. Ausschnitte und KI-Beobachtungen eines Fotos gehören zum Originalfoto,
    mehrere Zitate aus derselben Sprachnachricht/Mail/Notiz/demselben Dokument zur selben Quelle."""
    src, m = e.get("source"), e.get("meta") or {}
    if src in ("photo", "ai_vision"):
        if m.get("role") == "detail":
            return f"photo:{e.get('file') or e['evidence_id']}"
        return f"photo:{e.get('capture_id') or m.get('photo_evidence_id') or m.get('crop_of') or e['evidence_id']}"
    if src == "audio":
        return f"audio:{e.get('file') or e.get('capture_id') or e['evidence_id']}"
    if src in ("email", "note", "document"):
        return f"{src}:{e.get('capture_id') or e.get('file') or e['evidence_id']}"
    if src == "contract":
        return f"contract:{m.get('doc_id') or e.get('title') or e['evidence_id']}"
    return f"{src}:{e['evidence_id']}"


def _audio_transcript(cap: Optional[dict], file: Optional[str]) -> Optional[dict]:
    """Transkript der Datei: Sprachmemo selbst oder gesprochene Antwort auf eine Foto-Rückfrage."""
    if not cap:
        return None
    ans = cap.get("answer") or {}
    if file and ans.get("file") == file:
        return ans.get("transcript")
    return cap.get("transcript") or ans.get("transcript")


def evidence_sources(ids: list[str]) -> list[dict]:
    groups: dict[str, dict] = {}
    for eid in dict.fromkeys(ids):
        e = store.evidence(eid)
        if not e:
            continue
        key = source_key(e)
        cap = store.get("captures", e["capture_id"]) if e.get("capture_id") else None
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"key": key, "source": "photo" if e["source"] == "ai_vision" else e["source"],
                               "title": (cap or {}).get("title") or e.get("title"), "captured_at": e.get("captured_at"),
                               "capture_id": e.get("capture_id"), "file": None, "items": []}
            if e["source"] == "contract":
                g["title"] = e.get("title")
            if cap and cap.get("email"):
                g["email"] = cap["email"]
        item = {k: e.get(k) for k in ("evidence_id", "source", "title", "quote", "full_text", "t_start", "t_end",
                                      "asr_score", "page", "meta", "file", "captured_at")}
        g["items"].append(item)
        m = e.get("meta") or {}
        if g["source"] == "audio" and not g["file"]:
            g["file"], g["transcript"] = e.get("file"), _audio_transcript(cap, e.get("file"))
        if g["source"] == "photo" and not g["file"]:
            if e["source"] == "photo" and m.get("role") in (None, "original", "detail"):
                g["file"] = e.get("file")
            else:  # Ausschnitt/KI-Beobachtung → Originalfoto als Bild der Quelle
                orig = store.evidence(m.get("crop_of") or m.get("photo_evidence_id") or "") or {}
                g["file"] = orig.get("file") or (cap or {}).get("file")
            g["gps"] = m.get("gps")
    for g in groups.values():
        if g["source"] in ("email", "note", "document"):
            g["full_text"] = max((i.get("full_text") or "" for i in g["items"]), key=len)
    return list(groups.values())


def report_sections(project_id: str, day: str) -> dict[str, Any]:
    """Bericht-Abschnitte (daily_report.build) + Fortschritts-Erfassungen des Tages für die Seitenleiste „Captures“.

    Fortschritt = Erfassungen, deren Belege an einer Leistungszeile (§ 5) hängen, und alle Fotos (§ 8).
    """
    from sitevox.export import daily_report

    rep = daily_report.build(project_id, day)
    work_ev = {e for w in rep["work_performed"] for e in w.get("evidence_ids", [])}
    work_events = {i for w in rep["work_performed"] for i in w.get("event_ids", [])}
    caps = []
    for c in sorted(store.captures(project_id, day), key=lambda c: c["captured_at"]):
        linked = (c["kind"] == "photo" or work_ev & set(c.get("evidence_ids") or [])
                  or work_events & set(c.get("event_ids") or []))
        if not linked or c["kind"] not in ("photo", "audio", "note"):
            continue
        tr = c.get("transcript") or {}
        text = " ".join(sg["text"] for sg in tr.get("segments", [])) or c.get("text") or c.get("summary") or ""
        caps.append({"capture_id": c["capture_id"], "kind": c["kind"], "time": c["captured_at"][11:16],
                     "title": c.get("title"), "summary": c.get("summary"), "excerpt": text[:280],
                     "file": (c.get("file") or "").replace("\\", "/") or None,
                     "evidence_ids": c.get("evidence_ids") or []})
    return {**rep, "progress_captures": caps}
