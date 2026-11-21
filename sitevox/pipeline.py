"""Orchestrierung: Erfassung → Verstehen → Belege → Ereignisse → Regeln/Abweichung → (Entwurf auf Anforderung).

    Audio   → Whisper → Transkript (+Wort-Scores) → Qwen3-4B → Ereignis-JSON
    Foto    → Qwen3-VL → Beschreibung (+EXIF Zeit/GPS)
    Dokument→ Docling → Text/Tabellen (Protokolle → Zusammenfassung + offene Punkte)
    E-Mail  → .eml → Projektzuordnung → Qwen3-4B
Danach deterministisch: Aktivitätszuordnung, Risikosphäre, Schreiben-Empfehlung, Fristen, Konfidenz,
Soll-Ist/Prognose (engine). Die KI versendet nichts.
"""
from __future__ import annotations

import logging
import shutil
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from . import confidence as conf
from . import rag, settings, store
from .engine import deadlines, deviation, sphere as sph, weather
from .schemas import EVENT_TYPE_LABELS, Event, Evidence, ResourceEffect, ValueConf
from .understand import asr, documents, email_ingest, extract, vision

log = logging.getLogger(__name__)
KIND_TITLES = {"audio": "Sprachmemo", "photo": "Foto", "note": "Notiz", "email": "Mail", "document": "Dokument"}


# ============================================================================ evidence helpers
def new_evidence(**kw) -> Evidence:
    ev = Evidence(evidence_id=store.next_id("EV-", 4), **kw)
    store.save_evidence(ev)
    return ev


def _quote_evidence(cap: dict, quote: str, text: str) -> Evidence:
    base = dict(project_id=cap["project_id"], capture_id=cap["capture_id"], file=cap.get("file"),
                captured_at=cap["captured_at"], full_text=text, title=cap["title"])
    if cap["kind"] == "audio" and cap.get("transcript"):
        loc = asr.locate_quote(cap["transcript"], quote)
        if loc:
            return new_evidence(source="audio", quote=loc["text"], t_start=loc["t_start"], t_end=loc["t_end"],
                                asr_score=loc["asr_score"],
                                meta={"match_ratio": loc["match_ratio"], "low_words": loc["low_confidence_words"]},
                                **base)
        return new_evidence(source="audio", quote=quote, asr_score=cap.get("asr_score"),
                            meta={"match_ratio": 0, "warning": "Zitat nicht im Transkript gefunden"}, **base)
    src = {"email": "email", "note": "note", "document": "document", "photo": "photo"}[cap["kind"]]
    return new_evidence(source=src, quote=quote, meta={"found": quote[:40].lower() in text.lower()}, **base)


# ============================================================================ capture ingest
def ingest(project_id: str, kind: str, *, captured_at: str, file: Optional[Path] = None, text: Optional[str] = None,
           title: str = "", meta: Optional[dict] = None, fixture_key: Optional[str] = None,
           actor: str = "system") -> dict[str, Any]:
    meta = meta or {}
    day = captured_at[:10]
    cap: dict[str, Any] = {
        "capture_id": store.next_id(f"CAP-{day.replace('-', '')}-", 2), "project_id": project_id, "date": day,
        "kind": kind, "captured_at": captured_at, "status": "processing", "meta": meta,
        "title": title or f"{KIND_TITLES[kind]} {captured_at[11:16]}", "event_ids": [], "evidence_ids": [],
    }
    if file:
        dest = settings.project_files_dir(project_id, day) / Path(file).name
        if Path(file).resolve() != dest.resolve():
            shutil.copy(file, dest)
        cap["file"] = str(dest.relative_to(settings.data_dir()))
        file = dest
    store.save_capture(cap)
    try:
        return _ingest_body(cap, project_id, kind, captured_at, day, file, text, title, meta, fixture_key, actor)
    except Exception as e:  # noqa: BLE001 – Fehler sichtbar machen statt "processing" hängen zu lassen
        cap["status"], cap["error"] = "error", str(e)[:300]
        store.save_capture(cap)
        raise


def _ingest_body(cap, project_id, kind, captured_at, day, file, text, title, meta, fixture_key, actor) -> dict:
    acts = store.activities(project_id)

    # ---------------------------------------------------------------- understand
    body = text or ""
    if kind == "audio":
        tr = asr.transcribe(file, project_id, hint=text or meta.get("transcript_hint"), language=meta.get("language"))
        cap["transcript"], cap["asr_score"] = tr, tr.get("mean_score")
        body = tr["text"]
    elif kind == "photo":
        vis = vision.describe(file, project_id)
        cap["vision"] = vis
        body = vis.get("description", "")
    elif kind == "email":
        mail = email_ingest.parse_eml(file)
        mail["project_id"] = email_ingest.assign_project(mail) or project_id
        mail["capture_id"] = cap["capture_id"]
        store.save_email(mail)
        cap["email"] = {k: mail[k] for k in ("message_id", "from", "to", "subject", "received_at")}
        cap["title"] = title or f"Mail {captured_at[11:16]} · {mail['from'].split('<')[0].strip()}"
        body = f"Betreff: {mail['subject']}\nVon: {mail['from']}\n\n{mail['body']}"
    elif kind == "document":
        parsed = documents.parse(file)
        body = parsed["markdown"]
        doc = {"doc_id": meta.get("doc_id") or cap["capture_id"], "project_id": project_id,
               "title": meta.get("doc_title") or Path(file).stem, "file": cap["file"], "kind": meta.get("doc_type", "dokument"),
               "collection": "project", "pages": parsed["pages"], "tables": parsed["tables"]}
        store.save_document(doc)
        rag.index(rebuild=True)
        if meta.get("doc_type") == "protokoll":
            summ = extract.summarize_minutes(body, project_id=project_id, fixture_key=fixture_key)
            cap["minutes"] = summ.model_dump()
    cap["text"] = body

    _analyze(cap, body, acts, fixture_key)

    cap["status"] = "done"
    store.save_capture(cap)
    store.audit(actor, "capture", cap["capture_id"], "ingest", after={"kind": kind, "events": cap["event_ids"]})
    refresh_day(project_id, date.fromisoformat(day))
    return cap


def _analyze(cap: dict, body: str, acts: list[dict], fixture_key: Optional[str] = None) -> None:
    """Belege + Extraktion für eine Erfassung (auch für erneute Analyse nach manueller Korrektur)."""
    project_id, day, kind, meta, captured_at = cap["project_id"], cap["date"], cap["kind"], cap.get("meta", {}), \
        cap["captured_at"]
    cap["text"] = body
    source_ev = new_evidence(
        project_id=project_id, capture_id=cap["capture_id"],
        source={"audio": "audio", "photo": "photo", "email": "email", "note": "note", "document": "document"}[kind],
        title=cap["title"], file=cap.get("file"), quote=body[:280], full_text=body, captured_at=captured_at,
        asr_score=cap.get("asr_score"),
        meta={k: v for k, v in (cap.get("vision") or {}).items() if k in ("gps", "taken_at", "tags")},
    )
    cap["evidence_ids"].append(source_ev.evidence_id)

    # ---------------------------------------------------------------- extract (not for photos)
    if kind != "photo" and not (kind == "document" and meta.get("doc_type") != "protokoll"):
        res = extract.extract(body, project_id=project_id, date=day, time=captured_at[11:16], source=kind, acts=acts,
                              fixture_key=fixture_key)
        main, samples = res["main"], res["samples"]
        cap["summary"] = main.summary
        for p in main.progress:
            aid = extract.match_activity(p.activity, acts)
            if aid:
                ev = _quote_evidence(cap, p.quote, body)
                store.save_progress(project_id, aid, day, p.quantity, ev.evidence_id)
                cap["evidence_ids"].append(ev.evidence_id)
        crews = {c["name"]: c["planned_staff"] for c in settings.project_cfg(project_id).get("crews", [])}
        for s in main.staffing:
            ev = _quote_evidence(cap, s.quote, body)
            store.save_staffing(project_id, day, s.crew, s.present, crews.get(s.crew, s.present + (s.absent or 0)),
                                ev.evidence_id)
            cap["evidence_ids"].append(ev.evidence_id)
        for i, le in enumerate(main.events):
            same = [next((e for e in smp.events if e.type == le.type), None) for smp in samples]
            ev_id = _upsert_event(cap, le, same, body, acts)
            if ev_id not in cap["event_ids"]:
                cap["event_ids"].append(ev_id)
    else:
        cap["summary"] = body[:200]
        for e in store.events(project_id, day):
            names = [r for r in [x["resource"] for x in e.get("resource_effects", [])] + e["affected_activities"]]
            hit = meta["link_event_type"] == e["type"] if meta.get("link_event_type") else \
                any(n.split()[0].lower() in body.lower() for n in names if n)
            if hit and e["status"] != "dismissed":
                e["evidence"].append(source_ev.evidence_id)
                store.save_event(e)
                cap["event_ids"].append(e["event_id"])


# ============================================================================ events
def _text_agreement(main: str, others: list[Optional[str]]) -> float:
    vals = [SequenceMatcher(None, main or "", o or "").ratio() if o is not None else 0.0 for o in others]
    return sum(vals) / len(vals) if vals else 1.0


def _find_mergeable(project_id: str, day: str, typ: str, act_ids: list[str], resources: list[str]) -> Optional[dict]:
    for e in store.events(project_id, day):
        if e["type"] != typ or e["status"] in ("dismissed",):
            continue
        if set(act_ids) & set(e["activity_ids"]):
            return e
        er = {x["resource"].lower() for x in e.get("resource_effects", [])}
        if {r.lower() for r in resources} & er:
            return e
        if not act_ids and not resources and not e["activity_ids"] and not er:
            return e
    return None


def _upsert_event(cap: dict, le, same: list, body: str, acts: list[dict]) -> str:
    project_id, day = cap["project_id"], cap["date"]
    act_ids = [a for a in (extract.match_activity(n, acts) for n in le.affected_activities) if a]
    evs = [_quote_evidence(cap, q, body) for q in (le.quotes or [le.description])]
    ev_ids = [e.evidence_id for e in evs]
    cap["evidence_ids"].extend(ev_ids)
    asr_scores = [e.asr_score for e in evs if e.asr_score is not None]
    asr_mean = sum(asr_scores) / len(asr_scores) if asr_scores else None
    start_time = le.start_time or cap["captured_at"][11:16]

    stats = {
        "type": {"consistency": sum(1 for s in same if s) / max(len(same), 1)},
        "start": {"consistency": conf.agreement([(s.start_time if s else None) for s in same] or [le.start_time])[1]
                  if le.start_time else 0.5},
        "cause": {"consistency": _text_agreement(le.cause, [s.cause if s else None for s in same])},
        "affected_activities": {"consistency": conf.agreement(
            [sorted(a for a in (extract.match_activity(n, acts) for n in s.affected_activities) if a) if s else []
             for s in same])[1] if same else 1.0},
        "sphere_llm": {"values": [s.responsible_party_guess if s else "unklar" for s in same]},
        "impact_llm": {"values": [s.impact_estimate_days if s else None for s in same]},
        "blocked_until": {"consistency": conf.agreement([s.blocked_until if s else None for s in same])[1]
                          if le.blocked_until else None},
    }
    for k in stats:
        stats[k]["evidence"] = ev_ids
        stats[k]["asr"] = asr_mean

    existing = _find_mergeable(project_id, day, le.type, act_ids, [r.resource for r in le.resource_effects])
    effects = [ResourceEffect(resource=r.resource, status=r.status, start=r.start_time or start_time,
                              end=r.end_time).model_dump() for r in le.resource_effects]
    attrs_new = {k: getattr(le, k) for k in ("owner_supplied_material", "predecessor_by_owner", "own_work",
                                             "work_started", "ordered_by") if getattr(le, k) is not None}
    if existing:
        e = existing
        e["evidence"] = list(dict.fromkeys(e["evidence"] + ev_ids))
        e["activity_ids"] = list(dict.fromkeys(e["activity_ids"] + act_ids))
        e["affected_activities"] = list(dict.fromkeys(e["affected_activities"] + le.affected_activities))
        if le.blocked_until:
            e["blocked_until"] = le.blocked_until
        if le.end_time:
            e["end"] = f"{day}T{le.end_time}:00{cap['captured_at'][19:]}"
        for eff in effects:
            match = next((x for x in e["resource_effects"] if x["resource"].lower() == eff["resource"].lower()
                          and x["status"] == eff["status"]), None)
            if match:
                match["end"] = eff["end"] or match.get("end")
                if eff["start"] and eff["start"] < match["start"]:
                    match["start"] = eff["start"]
            else:
                e["resource_effects"].append(eff)
        e["attrs"].update(attrs_new)
        fs = e["attrs"].setdefault("field_stats", {})
        for k, v in stats.items():
            if k in fs:
                fs[k]["evidence"] = list(dict.fromkeys(fs[k]["evidence"] + ev_ids))
                if k == "blocked_until" and le.blocked_until:
                    fs[k]["consistency"] = v["consistency"]
                if k in ("sphere_llm", "impact_llm"):
                    fs[k]["values"] = fs[k]["values"] + v["values"]
            else:
                fs[k] = v
        store.save_event(e)
        return e["event_id"]

    eid = store.next_id(f"EVT-{day}-", 3)
    attrs = {**attrs_new, "field_stats": stats, "llm_sphere_guess": le.responsible_party_guess,
             "llm_sphere_rationale": le.responsible_rationale, "llm_impact_guess": le.impact_estimate_days}
    # Projektunterlagen gegenprüfen (RAG) – liefert Vertragsbeleg + Retrieval-Score
    if le.type == "additional_work":
        lv = rag.lv_contains(project_id, le.description)
        attrs["not_in_lv"] = not lv["found"]
        attrs["lv_relevance"] = lv["relevance"]
        q = (f"LV-Prüfung: keine passende LV-Position gefunden (beste Übereinstimmung "
             f"{lv['best']['doc_title']} S. {lv['best']['page']}, Relevanz {lv['relevance']:.2f})"
             if not lv["found"] and lv["best"] else
             f"LV-Prüfung: Treffer {lv['best']['doc_title']} S. {lv['best']['page']}" if lv["best"] else
             "LV-Prüfung: keine passende LV-Position gefunden")
        cev = new_evidence(project_id=project_id, source="contract", title="Leistungsverzeichnis", quote=q,
                           page=lv["best"]["page"] if lv["best"] else None,
                           full_text=lv["best"]["text"] if lv["best"] else "",
                           meta={"doc_id": lv["best"]["doc_id"] if lv["best"] else None,
                                 "relevance": 1 - lv["relevance"]})
        ev_ids.append(cev.evidence_id)
        stats["type"]["retrieval"] = round(1 - lv["relevance"], 3)
    elif le.type in ("planlieferverzug", "design_error", "leistungsaenderung"):
        query = le.description + " " + " ".join(le.affected_activities)
        hits = rag.index().search(query, project_id=project_id, collection="project", k=4)
        seen_docs: set[str] = set()
        for h in hits:
            if h["doc_id"] in seen_docs or len(seen_docs) >= 2:
                continue
            seen_docs.add(h["doc_id"])
            cev = new_evidence(project_id=project_id, source="contract", title=h["doc_title"], page=h["page"],
                               quote=rag.best_sentence(h["text"], query), full_text=h["text"],
                               meta={"doc_id": h["doc_id"], "relevance": h["relevance"]})
            ev_ids.append(cev.evidence_id)
        if hits:
            stats["type"]["retrieval"] = hits[0]["relevance"]
    rule_s, why = sph.rule_sphere(le.type, attrs)
    rec = sph.recommend(le.type, rule_s, attrs, affects_schedule=bool(act_ids))
    event = Event(
        event_id=eid, project_id=project_id, date=day, type=le.type, sphere=rule_s, sphere_rule=why,
        start=f"{day}T{start_time}:00{cap['captured_at'][19:]}",
        end=f"{day}T{le.end_time}:00{cap['captured_at'][19:]}" if le.end_time else None,
        detected_at=cap["captured_at"], affected_activities=le.affected_activities, activity_ids=act_ids,
        description=le.description, cause=le.cause, evidence=ev_ids, recommended_document=rec,
        resource_effects=[ResourceEffect(**x) for x in effects], blocked_until=le.blocked_until, attrs=attrs,
        status="open" if rec.requires_letter else "logged",
    )
    store.save_event(event)
    store.audit("ai", "event", eid, "create", after={"type": le.type, "sphere": rule_s, "doc": rec.kind})
    return eid


def _score_event(e: dict, analysis: dict, wx: Optional[dict]) -> dict:
    """Konfidenz je Feld + Regelchecks. Wird nach jeder Erfassung neu berechnet (deterministisch)."""
    fs = e["attrs"].get("field_stats", {})
    rows = {r["id"]: r for r in analysis.get("activities", [])}
    aff = [rows[a] for a in e["activity_ids"] if a in rows]
    e["on_critical_path"] = any(r["critical"] for r in aff)
    engine_delay = max([r["delay_days"] for r in aff] + [0]) if aff else None

    # Wetter: DWD-Abgleich entscheidet über Sphäre
    weather_exc = wx.get("assessment", {}).get("exceptional") if wx else None
    rule_s, why = sph.rule_sphere(e["type"], e["attrs"], weather_exc)
    if not e.get("sphere_confirmed"):
        e["sphere"], e["sphere_rule"] = rule_s, why
    rec = sph.recommend(e["type"], e["sphere"], e["attrs"], affects_schedule=bool(engine_delay))
    e["recommended_document"] = rec.model_dump()
    llm_guess, llm_agree = conf.agreement(fs.get("sphere_llm", {}).get("values", []) or ["unklar"])
    e["sphere_llm"] = {"party": llm_guess, "rationale": e["attrs"].get("llm_sphere_rationale", "")}
    e["warnings"] = sph.consistency_warnings(e["sphere"], rec.kind, llm_guess)
    if e["type"] == "additional_work" and e["attrs"].get("work_started"):
        e["warnings"].append("Ausführung bereits begonnen – Ankündigung muss VOR Ausführung erfolgen")
    if e["type"] == "additional_work" and e["attrs"].get("ordered_by") and "lechner" in str(
            e["attrs"]["ordered_by"]).lower():
        e["warnings"].append("Anordnung durch Architekt – Vollmacht prüfen, Ankündigung an AG richten")

    def F(key: str, **extra) -> dict:
        s = fs.get(key, {})
        return conf.combine(n_evidence=len(s.get("evidence", e["evidence"])), asr=s.get("asr"),
                            consistency=extra.get("consistency", s.get("consistency")),
                            retrieval=extra.get("retrieval", s.get("retrieval")), rule_ok=extra.get("rule_ok"))

    sphere_rule_ok = not any(w.startswith("Regelkonflikt") for w in e["warnings"])
    sphere_cons = sum(1 for v in fs.get("sphere_llm", {}).get("values", []) if v == e["sphere"]) / max(
        len(fs.get("sphere_llm", {}).get("values", [])), 1)
    fields = {
        "type": F("type"),
        "sphere": F("type", consistency=sphere_cons, rule_ok=sphere_rule_ok and llm_guess in (e["sphere"], "unklar")),
        "start": F("start"),
        "cause": F("cause"),
        "affected_activities": F("affected_activities", rule_ok=bool(e["activity_ids"]) or None),
    }
    if engine_delay is not None:
        # Wert rechnet die Engine; Unsicherheit kommt aus den Eingangsgrößen (z. B. "voraussichtlich Montag")
        bu = fs.get("blocked_until", {})
        llm_vals = [v for v in fs.get("impact_llm", {}).get("values", []) if v is not None]
        llm_cons = conf.agreement(llm_vals)[1] if llm_vals else None
        cons = min(x for x in [bu.get("consistency"), llm_cons] if x is not None) \
            if any(x is not None for x in [bu.get("consistency"), llm_cons]) else None
        imp = conf.combine(n_evidence=len(bu.get("evidence", e["evidence"])), asr=bu.get("asr"), consistency=cons,
                           rule_ok=None)
        if e.get("blocked_until") and "voraussichtlich" in " ".join(
                (store.evidence(i) or {}).get("quote", "") for i in e["evidence"]).lower():
            imp["value"] = round(imp["value"] * 0.7, 3)
            imp["band"] = conf.band(imp["value"])
            imp["reason"] = "Eingangsgröße nur 'voraussichtlich' zugesagt"
        e["impact_estimate_days"] = {"value": engine_delay, "confidence": imp["value"]}
        fields["impact_estimate_days"] = imp
    vals = [f["value"] for f in fields.values()]
    e["confidence"] = {"overall": round(sum(vals) / len(vals), 3), "fields": fields}
    e["deadline"] = deadlines.status(rec.kind, e["detected_at"], work_started=e["attrs"].get("work_started"),
                                     sent_at=e.get("sent_at"))
    e["label"] = EVENT_TYPE_LABELS[e["type"]]
    if e["status"] in ("open", "logged"):
        e["status"] = "open" if rec.requires_letter else "logged"
    return e


def refresh_day(project_id: str, day: date) -> dict[str, Any]:
    """Wetter + Soll-Ist + Prognose neu rechnen und Ereignisse neu bewerten."""
    wx = store.weather(project_id, day.isoformat())
    if wx is None:
        p = settings.project_cfg(project_id)
        try:
            raw = weather.fetch(p["lat"], p["lon"], day, project_id)
            s = weather.summarize(raw)
            wx = {"summary": s, "assessment": weather.assess(s)}
            store.save_weather(project_id, day.isoformat(), wx)
            ev = new_evidence(project_id=project_id, source="weather", title=f"DWD / Bright Sky {day:%d.%m.%Y}",
                              quote=_weather_text(s), full_text=_weather_text(s), captured_at=f"{day}T17:00:00",
                              meta=s)
            wx["evidence_id"] = ev.evidence_id
            store.save_weather(project_id, day.isoformat(), wx)
        except Exception as exc:  # noqa: BLE001 – Wetter ist optional
            log.warning("Wetter nicht verfügbar: %s", exc)
            wx = None
    analysis = deviation.analyze(project_id, day)
    for e in store.events(project_id, day.isoformat()):
        if e["type"] == "weather_interruption" and wx and wx.get("evidence_id") not in e["evidence"]:
            e["evidence"].append(wx["evidence_id"])
        store.save_event(_score_event(e, analysis, wx))
    return analysis


def _weather_text(s: dict) -> str:
    if not s.get("available"):
        return "keine Wetterdaten"
    t = (f"Temperatur {s['temp_min']:.0f} bis {s['temp_max']:.0f} °C, Niederschlag {s['precip_sum']:.1f} mm "
         f"(07–17 Uhr), Böen bis {s['gust_max']:.0f} km/h, {s.get('condition') or ''}")
    return t.replace(".", ",")


def dismiss_event(event_id: str, actor: str, note: str = "") -> dict:
    e = store.get("events", event_id)
    before = e["status"]
    e["status"] = "dismissed"
    store.save_event(e)
    store.audit(actor, "event", event_id, "dismiss", before=before, after="dismissed", note=note)
    return e


def confirm_sphere(event_id: str, sphere: str, actor: str) -> dict:
    e = store.get("events", event_id)
    before = e["sphere"]
    e["sphere"], e["sphere_confirmed"] = sphere, True
    store.save_event(e)
    store.audit(actor, "event", event_id, "confirm_sphere", before=before, after=sphere)
    refresh_day(e["project_id"], date.fromisoformat(e["date"]))
    return store.get("events", event_id)


def reset_sphere(event_id: str, actor: str) -> dict:
    """Bestätigung zurücknehmen: Sphäre wieder Vorschlag des Regelwerks (Empfehlung/Konfidenz neu berechnet)."""
    e = store.get("events", event_id)
    before = {"sphere": e["sphere"], "confirmed": e.get("sphere_confirmed", False)}
    e["sphere_confirmed"] = False
    store.save_event(e)
    refresh_day(e["project_id"], date.fromisoformat(e["date"]))
    e = store.get("events", event_id)
    store.audit(actor, "event", event_id, "reset_sphere", before=before, after={"sphere": e["sphere"], "confirmed": False})
    return e


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
