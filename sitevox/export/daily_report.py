"""Bautagesbericht als strukturierte Daten (Felder nach VHB Bund Richtlinie 411 + Quellenverweise).

Reine Datenaufbereitung aus Erfassungen, Engine (Soll-Ist, Tagesverlauf) und Ereignissen – kein LLM.
Was nicht erfasst wurde, bleibt leer (None) statt geschätzt; der Renderer zeigt dann "–".
Jede Zeile verweist über ``source_refs`` auf Einträge in ``sources`` (VOICE-01, MAIL-01, PHOTO-01, PLAN …).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from .. import settings, store
from ..engine import deviation, timeline
from ..schemas import DOC_KIND_LABELS

PREFIX = {"audio": "VOICE", "email": "MAIL", "photo": "PHOTO", "note": "NOTE", "document": "DOC"}
SOURCE_TYPE = {"audio": "Sprachnotiz", "email": "E-Mail", "photo": "Foto", "note": "Textnotiz", "document": "Dokument",
               "contract": "Vertrag / Protokoll", "weather": "Wetterdienst", "engine": "Bauzeitenplan"}
WEATHER_COND = {"dry": "trocken", "fog": "Nebel", "rain": "Regen", "sleet": "Schneeregen", "snow": "Schnee",
                "hail": "Hagel", "thunderstorm": "Gewitter"}
EVENT_STATUS = {"logged": "dokumentiert", "draft": "Entwurf", "open": "offen", "dismissed": "verworfen"}
RES_STATUS = {"idle": "Stillstand", "restricted": "eingeschränkt", "planned_not_started": "geplant, nicht begonnen",
              "work": "Arbeit"}
ALERT_SEVERITY = {"critical": "hoch", "warn": "mittel", "info": "niedrig"}
CONF_THRESHOLD = 0.8  # wie config/rules.toml: unter 0.8 gelb, unter 0.5 rot
SCHEMA = "sitevox.bautagesbericht/1"
FIELD_LABELS = {"type": "Ereignistyp", "sphere": "Risikosphäre", "start": "Beginn", "cause": "Ursache",
                "affected_activities": "betroffene Vorgänge", "impact_estimate_days": "Bauzeitauswirkung"}


def _hm(t: str) -> float:
    h, m = t.split(":")
    return int(h) + int(m) / 60


def _span(a: Optional[str], b: Optional[str]) -> float:
    return max(0.0, _hm(b) - _hm(a)) if a and b else 0.0


def _clean(text: Optional[str], limit: int = 700) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= limit else t[: limit - 1].rstrip() + " …"


def _name(addr: Optional[str]) -> Optional[str]:
    return addr.split("<")[0].strip().strip('"') if addr else None


def _posix(p: Optional[str]) -> Optional[str]:
    """Pfade relativ zu data/ immer mit „/“ (JSON soll plattformunabhängig sein)."""
    return p.replace("\\", "/") if p else p


# ------------------------------------------------------------------------------------------- sources
def _sources(pid: str, day: str, caps: list[dict], events: list[dict], wx: dict, acts: list[dict]):
    """Liefert (sources, cap_id → source_id, evidence_id → source_id)."""
    emails = {m.get("capture_id"): m for m in store.emails(pid)}
    sources: list[dict] = []
    by_cap: dict[str, str] = {}
    counter: dict[str, int] = {}
    for c in sorted(caps, key=lambda c: c["captured_at"]):
        pre = PREFIX.get(c["kind"], "SRC")
        counter[pre] = counter.get(pre, 0) + 1
        sid = f"{pre}-{counter[pre]:02d}"
        by_cap[c["capture_id"]] = sid
        tr = c.get("transcript") or {}
        lang = tr.get("language") or c.get("meta", {}).get("language") or "de"
        author = c.get("meta", {}).get("author")
        if c["kind"] == "email":
            m = emails.get(c["capture_id"]) or {}
            author = _name(m.get("from")) or author
            text = (f"Betreff: {m['subject']}. " if m.get("subject") else "") + _clean(m.get("body"), 600)
        elif tr.get("segments"):
            text = " ".join(s["text"] for s in tr["segments"])
        else:
            ev = store.evidence(c["evidence_ids"][0]) if c.get("evidence_ids") else None
            text = (ev or {}).get("full_text") or (ev or {}).get("quote") or c.get("summary") or c.get("title")
        sources.append({"source_id": sid, "type": SOURCE_TYPE.get(c["kind"], "Sonstiges"), "timestamp": c["captured_at"],
                        "author": author, "original_language": lang, "original_text": _clean(text),
                        "translation_de": tr.get("translation_de"), "file": _posix(c.get("file"))})

    by_ev: dict[str, str] = {}
    docs: dict[str, str] = {}
    ev_ids = list(dict.fromkeys(e for ev in events for e in ev.get("evidence", [])))
    if wx.get("evidence_id"):
        ev_ids.append(wx["evidence_id"])
    for eid in ev_ids:
        d = store.evidence(eid) or {}
        if d.get("capture_id") in by_cap:
            by_ev[eid] = by_cap[d["capture_id"]]
        elif d.get("source") == "weather":
            by_ev[eid] = "WEATHER-DWD"
        elif d.get("source") == "engine":
            by_ev[eid] = "PLAN"
        elif d.get("source") in ("contract", "document"):
            key = d.get("meta", {}).get("doc_id") or d.get("title") or eid
            if key not in docs:
                docs[key] = f"DOK-{len(docs) + 1:02d}"
                sources.append({"source_id": docs[key], "type": SOURCE_TYPE[d["source"]],
                                "timestamp": d.get("captured_at"), "author": d.get("title"),
                                "original_language": "de", "original_text": _clean(d.get("quote"), 400), "file": None})
            by_ev[eid] = docs[key]

    s = wx.get("summary") or {}
    if s.get("available"):
        sources.append({"source_id": "WEATHER-DWD", "type": "Wetterdienst", "timestamp": f"{day}T18:00:00",
                        "author": s.get("source", "DWD"), "original_language": "de",
                        "original_text": (f"{s.get('station', '')}: min {s['temp_min']:.1f} °C, max {s['temp_max']:.1f} °C, "
                                          f"Niederschlag {s['precip_sum']:.1f} mm, Böen bis {s['gust_max']:.0f} km/h."
                                          ).replace(".", ",").rstrip(",") + ".",
                        "file": None})
    plan = [f"{a['id']} {a['name']}: Tagessoll {a['today']['soll']:g} {a['unit']}" for a in acts if a["today"]["soll"]]
    sources.append({"source_id": "PLAN", "type": "Bauzeitenplan", "timestamp": None,
                    "author": settings.baseline()["company"]["name"], "original_language": "de",
                    "original_text": "; ".join(plan) or "Bauzeitenplan des Projekts", "file": None})
    return sources, by_cap, by_ev


# ------------------------------------------------------------------------------------------- build
def build(project_id: str, day: str) -> dict[str, Any]:
    project = settings.project_cfg(project_id)
    company = settings.baseline()["company"]
    a = deviation.analyze(project_id, date.fromisoformat(day))
    acts = {r["id"]: r for r in a["activities"]}
    wx = store.weather(project_id, day) or {}
    caps = store.captures(project_id, day)
    events = [e for e in store.events(project_id, day) if e.get("status") != "dismissed"]
    letters = {l["letter_id"]: l for l in store.letters(project_id)}
    tl = timeline.day_timeline(project_id, day, {r["id"] for r in a["activities"] if r["today"]["soll"]})
    sources, by_cap, by_ev = _sources(project_id, day, caps, events, wx, a["activities"])
    ev_by_id = {e["event_id"]: e for e in events}

    def refs(evidence_ids) -> list[str]:
        out = []
        for eid in evidence_ids:
            if eid not in by_ev:  # z. B. Personal-Belege, die an keinem Ereignis hängen
                cap = (store.evidence(eid) or {}).get("capture_id")
                if cap in by_cap:
                    by_ev[eid] = by_cap[cap]
            if eid in by_ev:
                out.append(by_ev[eid])
        return list(dict.fromkeys(out))

    resources = project.get("resources", [])
    start = min((r["from"] for r in resources), default=tl["start"])
    end = max((r["to"] for r in resources), default=tl["end"])
    signer = company.get("signer", "")

    # ---- Witterung
    s = wx.get("summary") or {}
    weather = None
    if s.get("available"):
        weather = {"condition": WEATHER_COND.get(s.get("condition"), s.get("condition") or "–"),
                   "temp_min_c": s["temp_min"], "temp_max_c": s["temp_max"], "precipitation_mm": s["precip_sum"],
                   "wind": f"Böen bis {s['gust_max']:.0f} km/h",
                   "work_possible": not wx.get("assessment", {}).get("exceptional", False),
                   "impact_note": "; ".join(wx.get("assessment", {}).get("reasons", [])) or None,
                   "source_refs": ["WEATHER-DWD"]}

    # ---- Personal: Ist je Kolonne aus Erfassung; nicht einzeln erfasste Kolonnen nur, wenn die Gesamtzahl aufgeht
    tl_rows = {r["name"]: r for r in tl["rows"]}
    res_by_name = {r["name"]: r for r in resources}
    staff = {r["crew"]: r for r in store.staffing(project_id, day)}
    crews = project.get("crews", [])
    known = {c["name"]: staff[c["name"]]["present"] for c in crews if c["name"] in staff}
    unknown = [c for c in crews if c["name"] not in staff]
    total = staff.get("Gesamt")
    derive = bool(total and unknown and total["present"] - sum(known.values()) == sum(c["planned_staff"] for c in unknown))
    workforce = []
    for c in crews:
        rec = staff.get(c["name"])
        count = rec["present"] if rec else (c["planned_staff"] if derive else None)
        refs_ = refs([rec["evidence_id"]]) if rec else (refs([total["evidence_id"]]) if derive else [])
        res = res_by_name.get(c["name"])
        span = _span(res["from"], res["to"]) if res else 0
        idle = sum(_span(sg["start"], sg["end"]) for sg in tl_rows.get(c["name"], {}).get("segments", [])
                   if sg["status"] == "idle")
        workforce.append({"company": company["name"], "crew": c["name"], "trade": c["trade"],
                          "planned": c["planned_staff"], "count": count,
                          "hours_total": count * span if count is not None and span else None,
                          "idle_hours": count * idle if count is not None and idle else 0,
                          "derived": bool(not rec and derive), "source_refs": refs_})

    # ---- Geräte: Zeilen des Tagesverlaufs, die keine Kolonne sind
    crew_names = {c["name"] for c in crews}
    equipment = []
    for row in tl["rows"]:
        if row["name"] in crew_names:
            continue
        res = res_by_name.get(row["name"], {})
        segs = row["segments"]
        operated = sum(_span(sg["start"], sg["end"]) for sg in segs if sg["status"] in ("work", "restricted"))
        down = [sg for sg in segs if sg["status"] in ("idle", "planned_not_started")]
        if down and not operated:
            status = "nicht eingesetzt"
        elif any(sg["status"] == "idle" for sg in segs):
            ev = ev_by_id.get(next((sg["event_id"] for sg in down if sg.get("event_id")), ""), {})
            status = "Ausfall" if ev.get("type") == "equipment_failure" else "Stillstand"
        else:
            status = "im Einsatz"
        causes = []
        for sg in down:
            ev = ev_by_id.get(sg.get("event_id") or "")
            if ev and ev["label"] not in causes:
                causes.append(f"{ev['label']}: {ev.get('cause') or ev.get('description')}")
        equipment.append({"name": row["name"], "status": status, "activity_id": row.get("activity_id"),
                          "hours_planned": _span(res.get("from"), res.get("to")) or None, "hours_operated": operated,
                          "downtime": [{"from": sg["start"], "to": sg["end"]} for sg in down],
                          "downtime_cause": "; ".join(dict.fromkeys(causes)) or None,
                          "source_refs": refs(e for sg in down for e in ev_by_id.get(sg.get("event_id") or "", {}).get("evidence", []))})

    # ---- Leistungen
    work = []
    for r in a["activities"]:
        if not (r["today"]["soll"] or r["today"]["ist"]):
            continue
        work.append({"activity_id": r["id"], "description": r["name"], "critical": r.get("critical", False),
                     "quantity_planned": r["today"]["soll"], "quantity_actual": r["today"]["ist"], "unit": r["unit"],
                     "ratio_pct": r["today"]["ratio"] * 100 if r["today"]["ratio"] is not None else None,
                     "progress_pct": (r.get("pct") or 0) * 100, "forecast_finish": r.get("forecast_finish"),
                     "delay_days": r.get("delay_days", 0), "source_refs": ["PLAN"]})

    # ---- Soll-Ist-Abweichungen (Engine-Alerts)
    deviations, milestones = [], []
    for al in a["alerts"]:
        act = acts.get(al["activity_id"], {})
        linked = al.get("events", [])
        # Reine Daten (Zahlen, ISO-Daten); Formatierung macht der Renderer
        if al["kind"] == "daily_output" and act:
            t = act["today"]
            deviations.append({"kind": "daily_output", "activity_id": act["id"], "metric": f"Tagesleistung {act['name']}",
                               "unit": act["unit"], "planned": t["soll"], "actual": t["ist"],
                               "deviation_pct": round((t["ratio"] - 1) * 100, 1) if t["ratio"] is not None else None,
                               "severity": ALERT_SEVERITY.get(al["severity"], al["severity"]),
                               "linked_incident_ids": linked})
        elif al["kind"] == "critical_delay" and act:
            deviations.append({"kind": "finish_delay", "activity_id": act["id"],
                               "metric": f"Fertigstellung {act['name']} (krit. Weg)", "unit": "Datum",
                               "planned": act.get("planned_finish"), "actual": act.get("forecast_finish"),
                               "delay_days": act.get("delay_days", 0),
                               "severity": "kritisch" if al["severity"] == "critical" else "mittel",
                               "linked_incident_ids": linked})
        elif al["kind"] == "milestone":
            milestones.append(al["message"])
    impact_chains = [ch["text"] for ch in a.get("impact", [])]

    # ---- Besondere Vorkommnisse
    incidents = []
    for ev in events:
        rec = ev.get("recommended_document") or {}
        letter = letters.get(ev.get("letter_id") or "")
        imp = []
        est = ev.get("impact_estimate_days") or {}
        if est.get("value"):
            conf = f"{est['confidence']:.2f}".replace(".", ",")
            imp.append(f"Bauzeit ca. {est['value']} AT (Konfidenz {conf})")
        if ev.get("on_critical_path"):
            imp.append("auf dem kritischen Weg")
        for re_ in ev.get("resource_effects", []):
            span = f"{re_['start']}–{re_['end']}" if re_.get("end") else f"ab {re_['start']}"
            imp.append(f"{re_['resource']}: {RES_STATUS.get(re_['status'], re_['status'])} {span} Uhr")
        if ev.get("blocked_until"):
            imp.append(f"blockiert bis {date.fromisoformat(ev['blocked_until']):%d.%m.%Y}")
        sphere_note = "bestätigt" if ev.get("sphere_confirmed") else "Vorschlag des Assistenten"
        # Regel entscheidet (deterministisch); KI-Einschätzung nur als Abgleich, Begründung nur bei Abweichung
        reasoning = ev.get("sphere_rule") or ""
        llm = ev.get("sphere_llm") or {}
        if llm.get("party") and llm["party"] == ev.get("sphere"):
            reasoning += " (Regelwerk; KI-Einschätzung übereinstimmend)"
        elif llm.get("party"):
            reasoning += f" (Regelwerk; KI-Einschätzung abweichend: {llm['party']} – {llm.get('rationale', '')})"
        notice = DOC_KIND_LABELS.get(rec.get("kind"), rec.get("kind") or "–")
        if rec.get("basis"):
            notice += f" ({rec['basis']})"
        dl = (ev.get("deadline") or {}).get("label")
        hint = "; ".join(x for x in [dl if dl and dl != "keine Frist" else None, rec.get("reason")] if x)
        status = f"{letter['letter_id']}: {letter['status']}" if letter else EVENT_STATUS.get(ev.get("status"), ev.get("status"))
        incidents.append({
            "incident_id": ev["event_id"], "type": ev.get("label") or ev["type"],
            "time": {"from": ev["start"][11:16], "to": ev["end"][11:16] if ev.get("end") else None},
            "description": ev.get("description"), "cause": ev.get("cause"),
            "responsibility_sphere": ev.get("sphere"), "sphere_note": sphere_note, "sphere_reasoning": reasoning or None,
            "warnings": ev.get("warnings", []),
            "affected_activities": [f"{i} {acts[i]['name']}" if i in acts else i for i in ev.get("activity_ids", [])],
            "impact": imp, "suggested_notice": notice, "notice_deadline_hint": hint or None,
            "notice_status": status, "confidence": (ev.get("confidence") or {}).get("overall"),
            "source_refs": refs(ev.get("evidence", [])),
        })

    # ---- Fotos
    photos = []
    for c in caps:
        if c["kind"] != "photo":
            continue
        ev = store.evidence(c["evidence_ids"][0]) if c.get("evidence_ids") else {}
        gps = (ev or {}).get("meta", {}).get("gps")
        photos.append({"photo_id": by_cap[c["capture_id"]], "file": _posix((ev or {}).get("file") or c.get("file")),
                       "timestamp": c["captured_at"],
                       "location": f"GPS {gps['lat']:.5f}, {gps['lon']:.5f}" if gps else None,
                       "caption_de": (ev or {}).get("quote") or c.get("summary") or c.get("title"),
                       "related_ids": c.get("event_ids", [])})

    # ---- Prüfung (Human in the loop)
    unsupported, uncertain, questions = [], [], []
    for ev in events:
        letter = letters.get(ev.get("letter_id") or "")
        if letter:
            kind = DOC_KIND_LABELS.get(letter["kind"], letter["kind"])
            for iss in letter.get("issues", []):
                if iss.get("status") == "unverified":
                    unsupported.append(f"{kind} {letter['letter_id']}: „{iss['value']}“ – {iss.get('message') or 'ohne Beleg'}")
            if letter["status"] == "Entwurf":
                dl = (ev.get("deadline") or {}).get("label")
                questions.append(f"{kind} {letter['letter_id']} zu {ev['event_id']} prüfen und freigeben"
                                 + (f" (Frist: {dl})" if dl and dl != "keine Frist" else "") + "?")
        for f, v in ((ev.get("confidence") or {}).get("fields") or {}).items():
            if v.get("value") is not None and v["value"] < CONF_THRESHOLD:
                conf = f"{v['value']:.2f}".replace(".", ",")
                uncertain.append(f"{ev['event_id']} ({ev.get('label')}): {FIELD_LABELS.get(f, f)} nur Konfidenz {conf}")
        if not ev.get("sphere_confirmed"):
            questions.append(f"Risikosphäre {ev.get('sphere')} für {ev['event_id']} ({ev.get('label')}) bestätigen?")
        for w in ev.get("warnings", []):
            questions.append(f"{ev['event_id']}: {w}")
    if any(w.get("derived") for w in workforce):
        uncertain.append("Personal: nicht einzeln erfasste Kolonnen aus der Gesamtzahl abgeleitet (Ist = Soll angenommen).")

    return {
        "meta": {
            "schema": SCHEMA, "generated_at": store.now_iso(),
            "report_id": f"TB-{day}", "date": day, "report_no": a.get("today_idx"),
            "project": {"name": project.get("title") or project.get("name"), "project_no": project["id"],
                        "contract_no": project.get("contract_no"), "address": project.get("address")},
            "contractor": {"company": company["name"], "bauleiter": signer.split(",")[0].strip(),
                           "address": company.get("address"), "polier": project.get("polier")},
            "client": {"name": project["client"]["name"],
                       "representative": ", ".join(x for x in [project["client"].get("representative"),
                                                               project["client"].get("representative_role")] if x)},
            "author": signer, "working_hours": {"start": start, "end": end},
        },
        "weather": weather, "workforce": workforce, "equipment": equipment, "deliveries": [],
        "work_performed": work, "deviations": deviations, "milestones_at_risk": milestones,
        "impact_chains": impact_chains, "incidents": incidents, "photos": photos, "sources": sources,
        "review": {"status": "KI-Entwurf", "ai_generated": True, "unsupported_statements": unsupported,
                   "uncertain": uncertain, "open_questions": questions},
    }


def export_files(project_id: str, day: str) -> dict[str, str]:
    """Baut den Bericht einmal, verpixelt Fotos und schreibt PDF, DOCX und JSON (gleicher Inhalt, gleiches Layout)."""
    import json

    from . import privacy, report_docx, report_pdf

    data = build(project_id, day)
    out_dir = settings.project_files_dir(project_id, day) / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    photo_files = {}
    for ph in data["photos"]:
        src = settings.data_dir() / ph["file"] if ph.get("file") else None
        if not src or not src.exists():
            continue
        dst = out_dir / f"anon_{src.name}"
        try:
            privacy.blur_faces(src, dst)
            photo_files[ph["photo_id"]] = dst
        except Exception:  # Foto unlesbar → im Bericht "nicht verfügbar", Export läuft weiter
            pass
    base = out_dir / f"Bautagesbericht_{project_id}_{day}"
    base.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    report_pdf.render(data, base.with_suffix(".pdf"), photo_files)
    report_docx.render(data, base.with_suffix(".docx"), photo_files)
    return {fmt: str(base.with_suffix(f".{fmt}")) for fmt in ("pdf", "docx", "json")}
