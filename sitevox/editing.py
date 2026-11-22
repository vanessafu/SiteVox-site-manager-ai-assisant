"""Manuelle Bearbeitung und Löschung durch die Bauleitung.

Grundsätze
  * Jede Änderung geht ins Audit-Log (vorher/nachher).
  * Abgeleitete Werte (KPIs, Gantt, Prognose, Konfidenz) werden NICHT direkt editiert, sondern aus den
    bearbeiteten Eingaben neu berechnet (refresh_day).
  * Belege, die in einem freigegebenen/versendeten Schreiben stecken, dürfen nicht gelöscht werden
    (Nachweisfunktion). Entwürfe werden neu geprüft – fehlende Belege erscheinen dort rot.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from . import rag, settings, store
from .engine import schedule

LOCKED_LETTER = ("Geprüft", "Versendet")


class EditError(ValueError):
    pass


# ============================================================================ Projekt-Stammdaten
PROJECT_FIELDS = ("name", "title", "address", "contract_no", "contract_date", "contract_basis", "lat", "lon")
CLIENT_FIELDS = ("name", "address", "representative", "representative_role", "email", "phone")


def update_project(project_id: str, patch: dict, actor: str) -> dict:
    p = dict(settings.project_cfg(project_id))
    before = {k: p.get(k) for k in PROJECT_FIELDS} | {"client": dict(p.get("client", {}))}
    for k in PROJECT_FIELDS:
        if k in patch:
            p[k] = patch[k]
    if "coords" in patch:
        p["lat"], p["lon"] = parse_coords(patch["coords"]) if (patch["coords"] or "").strip() else (None, None)
        store.delete_weather(project_id)  # neuer Standort → Wetter neu holen
    if "client" in patch:
        p["client"] = {**p.get("client", {}), **{k: v for k, v in patch["client"].items() if k in CLIENT_FIELDS}}
        if "email" in patch["client"]:  # von der Bauleitung eingetragen → darf als Empfänger vorgeschlagen werden
            p["client"]["email_source"] = "manual" if patch["client"]["email"] else None
    if "crews" in patch:
        p["crews"] = patch["crews"]
    if "resources" in patch:
        p["resources"] = patch["resources"]
    store.save_project(p)
    store.audit(actor, "project", project_id, "edit", before=before, after=patch)
    return p


# ============================================================================ Bauzeitenplan
def _normalize(project_id: str, a: dict) -> dict:
    if isinstance(a.get("preds"), str):
        a["preds"] = schedule.parse_preds(a["preds"])
    if isinstance(a.get("aliases"), str):
        a["aliases"] = [x.strip() for x in a["aliases"].split(";") if x.strip()]
    a["kind"] = a.get("kind") or "task"
    a["qty"] = float(a.get("qty") or 0)
    a["lv_sum"] = float(a.get("lv_sum") or 0)
    if a["kind"] == "milestone":
        a["start"] = a["finish"]
    s, f = date.fromisoformat(a["start"]), date.fromisoformat(a["finish"])
    if f < s:
        raise EditError("Ende liegt vor dem Anfang")
    others = [x for x in store.activities(project_id) if x["id"] != a["id"]]
    origin = min([s] + [date.fromisoformat(x["start"]) for x in others])
    cal = schedule.WorkCalendar(origin)
    a["duration"] = 0 if a["kind"] == "milestone" else cal.between(s, f) + 1
    all_acts = others + [a]
    ids = {x["id"] for x in all_acts}
    for p in a["preds"]:
        if p["id"] not in ids:
            raise EditError(f"Vorgänger {p['id']} existiert nicht")
    try:
        schedule.cpm(all_acts, cal)  # Zyklen etc. prüfen
    except ValueError as e:
        raise EditError(str(e)) from e
    return a


def save_activity(project_id: str, activity_id: Optional[str], data: dict, actor: str) -> dict:
    existing = {a["id"]: a for a in store.activities(project_id)}
    if activity_id is None:  # neu
        if not data.get("id"):
            n = 10 * (len(existing) + 1)
            while f"A{n}" in existing:
                n += 10
            data["id"] = f"A{n}"
        if data["id"] in existing:
            raise EditError(f"ID {data['id']} existiert bereits")
        before = None
        a = {"preds": [], "aliases": [], "unit": "", "lv_pos": "", **data}
    else:
        if activity_id not in existing:
            raise EditError("Vorgang nicht gefunden")
        before = existing[activity_id]
        a = {**before, **data, "id": activity_id}
    a = _normalize(project_id, a)
    store.save_activity(project_id, a)
    store.audit(actor, "activity", f"{project_id}/{a['id']}", "create" if before is None else "edit",
                before=before, after=a)
    return a


def delete_activity(project_id: str, activity_id: str, actor: str) -> None:
    acts = store.activities(project_id)
    users = [a["id"] for a in acts if any(p["id"] == activity_id for p in a["preds"])]
    if users:
        raise EditError(f"Vorgang ist Vorgänger von {', '.join(users)} – dort zuerst entfernen")
    before = next((a for a in acts if a["id"] == activity_id), None)
    store.delete_activity(project_id, activity_id)
    store.audit(actor, "activity", f"{project_id}/{activity_id}", "delete", before=before)


def set_progress(project_id: str, activity_id: str, day: str, qty: Optional[float], actor: str) -> None:
    """Manuelle Korrektur = neuer Tageswert; ersetzt alle Einzelmeldungen des Tages (Belege bleiben verknüpft)."""
    prev = [p for p in store.progress(project_id) if p["activity_id"] == activity_id and p["date"] == day]
    store.execute("DELETE FROM progress_reports WHERE project_id=? AND activity_id=? AND date=?",
                  (project_id, activity_id, day))
    if qty is None:
        store.execute("DELETE FROM progress WHERE project_id=? AND activity_id=? AND date=?",
                      (project_id, activity_id, day))
    else:
        # als eine Meldung ablegen, damit spätere Meldungen desselben Tages darauf aufaddiert werden
        store.add_progress_report(project_id, activity_id, day, float(qty),
                                  (prev[0]["evidence_id"] if prev and prev[0]["evidence_id"] else None)
                                  or f"manual:{store.now_iso()}")
    store.audit(actor, "progress", f"{project_id}/{activity_id}/{day}", "edit",
                before=prev[0]["qty"] if prev else None, after=qty, note="manuelle Korrektur Ist-Menge")


def set_staffing(project_id: str, day: str, crew: str, present: Optional[int], planned: Optional[int],
                 actor: str) -> None:
    prev = [s for s in store.staffing(project_id, day) if s["crew"] == crew]
    store.execute("DELETE FROM staffing_reports WHERE project_id=? AND date=? AND crew=?", (project_id, day, crew))
    if present is None:
        store.execute("DELETE FROM staffing WHERE project_id=? AND date=? AND crew=?", (project_id, day, crew))
    else:
        store.add_staffing_report(project_id, day, crew, int(present), int(planned if planned is not None else present),
                                  (prev[0]["evidence_id"] if prev and prev[0]["evidence_id"] else None)
                                  or f"manual:{store.now_iso()}")
    store.audit(actor, "staffing", f"{project_id}/{day}/{crew}", "edit", before=prev[0] if prev else None,
                after={"present": present, "planned": planned})


# ============================================================================ Berichtszeilen (Personal / Geräte)
REPORT_FIELDS = {
    "workforce": {"company": str, "trade": str, "planned": int, "count": int, "hours_total": float, "idle_hours": float},
    "equipment": {"status": str, "hours_planned": float, "hours_operated": float, "downtime": list,
                  "downtime_cause": str},
    # Leistungen / Projektübersicht (Schlüssel = Vorgangsbezeichnung)
    "work": {"activity_id": str, "progress_pct": float, "quantity_planned": float, "quantity_actual": float,
             "unit": str, "planned_finish": str, "forecast_finish": str, "delay_days": int},
    # Lieferungen § 4 (Schlüssel = Material)
    "deliveries": {"supplier": str, "quantity": float, "unit": str, "planned_time": str, "actual_time": str,
                   "delay_minutes": int, "status": str, "delivery_note_no": str, "supplied_by": str},
    # Tagesbuch: Prüfungen, Besuche, erledigte Arbeiten … (Schlüssel = log_id, neue Einträge M-…)
    "site_log": {"time": str, "label": str, "text": str, "detail": str},
}


def _coerce(typ, v):
    if v is None or v == "":
        return None
    if typ is list:
        return [{"from": str(x.get("from") or ""), "to": (str(x["to"]) if x.get("to") else None)} for x in v
                if x.get("from")]
    return typ(v)


def set_report_row(project_id: str, day: str, section: str, key: str, data: Optional[dict], action: str,
                   actor: str) -> None:
    """Manuelle Korrektur einer Zeile im Bautagesbericht (§ 2 Personal, § 3 Geräte).

    action: "set" (Felder überschreiben bzw. neue Zeile), "delete" (Zeile ausblenden), "reset" (Korrektur verwerfen).
    Gilt für Dashboard und PDF/DOCX gleichermaßen, weil beide aus daily_report.build lesen.
    """
    if section not in REPORT_FIELDS:
        raise EditError(f"Abschnitt {section} nicht bearbeitbar")
    key = (key or "").strip()
    if not key:
        raise EditError("Name fehlt")
    prev = store.report_rows(project_id, day, section).get(key)
    if action == "reset":
        doc = None
    elif action == "delete":
        doc = {"deleted": True}
    else:
        fields = REPORT_FIELDS[section]
        doc = {k: v for k, v in (prev or {}).items() if k != "deleted"}
        for k, v in (data or {}).items():
            if k in fields:
                doc[k] = _coerce(fields[k], v)
    store.save_report_row(project_id, day, section, key, doc)
    store.audit(actor, "report_row", f"{project_id}/{day}/{section}/{key}", action, before=prev, after=doc)


# ============================================================================ Ereignisse
EVENT_FIELDS = ("type", "description", "cause", "start", "end", "blocked_until", "affected_activities",
                "resource_effects")


def update_event(event_id: str, patch: dict, actor: str) -> dict:
    from .pipeline import refresh_day
    from .understand.extract import match_activity

    e = store.get("events", event_id)
    if not e:
        raise EditError("Ereignis nicht gefunden")
    before = {k: e.get(k) for k in EVENT_FIELDS}
    for k in EVENT_FIELDS:
        if k in patch:
            e[k] = patch[k] or (None if k in ("end", "blocked_until") else patch[k])
    if "affected_activities" in patch:
        acts = store.activities(e["project_id"])
        e["activity_ids"] = [a for a in (match_activity(n, acts) for n in e["affected_activities"]) if a]
    for k in ("work_started", "owner_supplied_material", "predecessor_by_owner", "own_work"):
        if k in patch:
            e["attrs"][k] = patch[k]
    e["attrs"]["manually_edited"] = True
    store.save_event(e)
    store.audit(actor, "event", event_id, "edit", before=before, after={k: patch[k] for k in patch})
    refresh_day(e["project_id"], date.fromisoformat(e["date"]))
    return store.get("events", event_id)


def delete_event(event_id: str, actor: str) -> None:
    e = store.get("events", event_id)
    if not e:
        return
    if e.get("letter_id"):
        l = store.get("letters", e["letter_id"])
        if l and l["status"] in LOCKED_LETTER:
            raise EditError("Ereignis gehört zu einem freigegebenen/versendeten Schreiben")
        if l:
            store.delete("letters", l["letter_id"])
    store.delete("events", event_id)
    store.audit(actor, "event", event_id, "delete", before={"type": e["type"], "description": e["description"]})
    from .pipeline import refresh_day

    refresh_day(e["project_id"], date.fromisoformat(e["date"]))


# ============================================================================ Erfassungen
def _purge_derived(cap: dict, actor: str, *, keep_source: bool, keep: Optional[set[str]] = None) -> dict:
    """Entfernt alles, was aus einer Erfassung abgeleitet wurde. Gibt eine Zusammenfassung zurück.
    keep: Belege, die erhalten bleiben (z. B. Foto, Ausschnitte, KI-Beobachtungen bei erneuter Analyse)."""
    from .drafting import composer

    evs = store.evidence_by_capture(cap["capture_id"])
    ids = {e["evidence_id"] for e in evs}
    source_id = cap["evidence_ids"][0] if cap.get("evidence_ids") else None
    remove = ids - ({source_id} if keep_source and source_id else set()) - (keep or set())

    for l in store.letters(cap["project_id"]):
        if l["status"] in LOCKED_LETTER and remove & set(l["evidence_map"].values()):
            raise EditError(f"Beleg wird in Schreiben {l['letter_id']} ({l['status']}) verwendet – "
                            "Löschen nicht zulässig (Nachweis)")
    summary = {"evidence": len(remove), "progress": 0, "staffing": 0, "events_deleted": [], "letters_rechecked": []}
    if remove:
        q = ",".join("?" * len(remove))
        summary["progress"], summary["staffing"] = store.delete_reports_by_evidence(remove)
        summary["log_entries"] = store.delete_log_entries_by_evidence(remove)
    for e in store.events(cap["project_id"]):
        if not remove & set(e["evidence"]):
            continue
        e["evidence"] = [x for x in e["evidence"] if x not in remove]
        for st in e["attrs"].get("field_stats", {}).values():
            if "evidence" in st:
                st["evidence"] = [x for x in st["evidence"] if x not in remove]
        raw_left = [x for x in e["evidence"] if (store.evidence(x) or {}).get("capture_id")]
        if not raw_left:
            delete_event(e["event_id"], actor)
            summary["events_deleted"].append(e["event_id"])
        else:
            store.save_event(e)
    for l in store.letters(cap["project_id"]):
        if l["status"] == "Entwurf" and remove & set(l["evidence_map"].values()):
            l["evidence_map"] = {k: v for k, v in l["evidence_map"].items() if v not in remove}
            store.save_letter(composer.reverify(l))
            summary["letters_rechecked"].append(l["letter_id"])
    for eid in remove:
        store.delete("evidence", eid)
    return summary


def delete_capture(capture_id: str, actor: str) -> dict:
    from .pipeline import refresh_day

    cap = store.get("captures", capture_id)
    if not cap:
        raise EditError("Erfassung nicht gefunden")
    # Abgeleitete Dateien (Foto-Ausschnitte, Detailfoto, Sprachantwort) gehören zur Erfassung
    derived_files = {e["file"] for e in store.evidence_by_capture(capture_id) if e.get("file")} | \
        {(cap.get("answer") or {}).get("file")}
    derived_files -= {None, cap.get("file")}
    summary = _purge_derived(cap, actor, keep_source=False)
    store.execute("DELETE FROM emails WHERE json_extract(doc, '$.capture_id')=?", (capture_id,))
    doc_id = (cap.get("meta") or {}).get("doc_id") or capture_id
    if cap["kind"] == "document" and store.get("documents", doc_id):
        store.delete("documents", doc_id)
        rag.index(rebuild=True)
    if cap.get("file"):
        f = (settings.data_dir() / cap["file"]).resolve()
        if str(f).startswith(str(settings.data_dir().resolve())) and f.is_file():
            f.unlink()
            summary["file_deleted"] = cap["file"]
    for rel in derived_files:
        f = (settings.data_dir() / rel).resolve()
        if str(f).startswith(str((settings.data_dir() / cap["project_id"]).resolve())) and f.is_file():
            f.unlink()
            summary.setdefault("derived_files_deleted", []).append(rel)
    store.delete("captures", capture_id)
    store.audit(actor, "capture", capture_id, "delete", before={"kind": cap["kind"], "title": cap["title"],
                                                                 "file": cap.get("file")}, after=summary)
    refresh_day(cap["project_id"], date.fromisoformat(cap["date"]))
    return summary


def update_capture(capture_id: str, patch: dict, actor: str) -> dict:
    """Titel/Zusammenfassung/Text korrigieren; mit reanalyze=True wird der (korrigierte) Text neu ausgewertet."""
    from .pipeline import _analyze, refresh_day

    cap = store.get("captures", capture_id)
    if not cap:
        raise EditError("Erfassung nicht gefunden")
    before = {k: cap.get(k) for k in ("title", "summary", "text")}
    for k in ("title", "summary"):
        if k in patch:
            cap[k] = patch[k]
    text_changed = "text" in patch and patch["text"] != cap.get("text")
    if text_changed:
        cap["text"] = patch["text"]
        cap["text_edited"] = True
    if patch.get("reanalyze") and cap["kind"] == "photo":
        # Foto, Ausschnitte und KI-Beobachtungen bleiben; die (korrigierte) Antwort wird neu ausgewertet
        from .pipeline import _photo_finalize

        ph = cap.get("photo") or {}
        keep = {x for x in [ph.get("evidence_id"), ph.get("detail_evidence_id")] +
                [r.get("crop_evidence_id") for r in ph.get("observations", [])] +
                [r.get("ai_evidence_id") for r in ph.get("observations", [])] if x}
        _purge_derived(cap, actor, keep_source=False, keep=keep)
        for e in store.events(cap["project_id"]):  # Ereignisse, die nur noch am Foto hängen, entstehen neu
            if keep & set(e["evidence"]):
                others = [x for x in e["evidence"] if x not in keep and (store.evidence(x) or {}).get("capture_id")]
                if not others:
                    delete_event(e["event_id"], actor)
                else:
                    e["evidence"] = [x for x in e["evidence"] if x not in keep]
                    store.save_event(e)
        cap["evidence_ids"] = [x for x in cap["evidence_ids"] if x in keep]
        cap["event_ids"] = []
        if text_changed and cap.get("answer"):
            cap["answer"] = {**cap["answer"], "mode": "note", "transcript": None, "edited": True}
        _photo_finalize(cap, cap.get("text") or "", store.activities(cap["project_id"]))
        cap["status"] = "done"
    elif patch.get("reanalyze"):
        _purge_derived(cap, actor, keep_source=False)
        cap["evidence_ids"], cap["event_ids"] = [], []
        if cap.get("transcript") and text_changed:
            cap["transcript"] = None  # Wort-Zeitstempel passen nicht mehr zum korrigierten Text
        _analyze(cap, cap["text"], store.activities(cap["project_id"]), fixture_key=None)
    store.save_capture(cap)
    store.audit(actor, "capture", capture_id, "edit", before=before,
                after={k: patch.get(k) for k in ("title", "summary", "text", "reanalyze") if k in patch})
    refresh_day(cap["project_id"], date.fromisoformat(cap["date"]))
    return cap


def delete_document(doc_id: str, actor: str) -> None:
    d = store.get("documents", doc_id)
    if not d:
        raise EditError("Dokument nicht gefunden")
    if d["project_id"] == "_legal":
        raise EditError("Rechtsgrundlagen sind schreibgeschützt")
    if store.get("captures", doc_id):  # per Upload erfasst → Erfassung inkl. Datei löschen
        delete_capture(doc_id, actor)
        return
    store.delete("documents", doc_id)
    if d.get("file") and str(d["file"]).startswith(d["project_id"] + "/"):
        f = settings.data_dir() / d["file"]
        if f.is_file():
            f.unlink()
    rag.index(rebuild=True)
    store.audit(actor, "document", doc_id, "delete", before={"title": d["title"], "file": d.get("file")})


def capture_file_path(cap: dict) -> Optional[Path]:
    return settings.data_dir() / cap["file"] if cap.get("file") else None


def parse_coords(text: str) -> tuple[float, float]:
    """„48.1305, 11.6955“ (Google Maps) oder „48,1305 11,6955“ → (Breite, Länge)."""
    import re

    nums = re.findall(r"-?\d+(?:[.,]\d+)?", text or "")
    if len(nums) == 4 and "," in text and "." not in text:  # 48,1305, 11,6955
        nums = [f"{nums[0]}.{nums[1]}", f"{nums[2]}.{nums[3]}"]
    if len(nums) != 2:
        raise EditError("Koordinaten als „Breite, Länge“ angeben, z. B. 48.1305, 11.6955")
    lat, lon = (float(n.replace(",", ".")) for n in nums)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise EditError("Koordinaten außerhalb des gültigen Bereichs")
    return round(lat, 5), round(lon, 5)


# ============================================================================ Projekte anlegen / löschen
def create_project(data: dict, actor: str) -> dict:
    """Neues, leeres Projekt. Kennung aus dem Kurznamen („BV Pasing“ → BV-PASING), eindeutig gemacht."""
    import re

    name = (data.get("name") or "").strip()
    if not name:
        raise EditError("Kurzname fehlt")
    base = re.sub(r"[^A-Z0-9]+", "-", name.upper().replace("Ä", "AE").replace("Ö", "OE").replace("Ü", "UE")
                  .replace("ß", "SS")).strip("-") or "PROJEKT"
    if not base.startswith("BV"):
        base = f"BV-{base}"
    ids = {p["id"] for p in store.list_projects()}
    pid, n = base, 2
    while pid in ids:
        pid, n = f"{base}-{n}", n + 1
    g = lambda k: (data.get(k) or "").strip()  # noqa: E731
    p = {"id": pid, "name": name, "title": g("title") or name, "address": g("address"),
         "contract_no": g("contract_no"), "contract_date": g("contract_date") or None,
         "contract_basis": g("contract_basis") or "VOB/B (aktuelle Fassung) als Vertragsbestandteil vereinbart",
         "client": {"name": g("client_name") or "N. N.", "address": g("client_address"),
                    "representative": g("client_representative") or "N. N.", "email": g("client_email"),
                    "email_source": "manual" if g("client_email") else None},
         "parties": [], "crews": [], "resources": [], "milestones": []}
    if g("coords"):
        p["lat"], p["lon"] = parse_coords(g("coords"))
    if g("client_email") and not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", g("client_email")):
        raise EditError(f"Keine gültige E-Mail-Adresse: {g('client_email')}")
    store.save_project(p)
    store.audit(actor, "project", pid, "create", after=p)
    return p


def delete_project(project_id: str, actor: str) -> dict:
    if project_id not in {p["id"] for p in store.list_projects()}:
        raise KeyError(project_id)
    before = settings.project_cfg(project_id)
    counts = store.delete_project(project_id)
    store.audit(actor, "project", project_id, "delete", before={"name": before.get("name"), "title": before.get("title")},
                after=counts)
    return counts


def import_schedule(project_id: str, path: Path, actor: str) -> dict:
    """Bauzeitenplan (xlsx/csv) einlesen; ersetzt die bisherigen Vorgänge des Projekts."""
    try:
        acts = schedule.import_plan(path)
    except Exception as e:  # noqa: BLE001 – Datei unlesbar/falsches Format
        raise EditError(f"Bauzeitenplan nicht lesbar ({e})") from e
    if not acts:
        raise EditError("Keine Vorgänge im Bauzeitenplan gefunden")
    c = store.connect()
    c.execute("DELETE FROM activities WHERE project_id=?", (project_id,))
    c.commit()
    for a in acts:
        store.save_activity(project_id, a)
    store.audit(actor, "project", project_id, "schedule_import", after={"file": Path(path).name, "activities": len(acts)})
    return {"activities": len(acts)}


# ============================================================================ Rechtsgrundlagen pflegen
LEGAL = "_legal"


def _legal_sections(text: str) -> str:
    """Hochgeladene Gesetzestexte (PDF/DOCX) haben keine Markdown-Überschriften → vor jedem „§ n“ einen Abschnitt
    beginnen, damit die Suche je Paragraph trifft (wie bei den mitgelieferten .md-Texten)."""
    import re

    if re.search(r"(?m)^## ", text):
        return text
    return re.sub(r"(?m)^\s*(§{1,2}\s*\d+[a-z]?\b[^\n]{0,160})$", r"## \1", text)


def upload_legal(path: Path, title: str, version: str, replaces: Optional[str], actor: str) -> dict:
    """Neue Rechtsgrundlage bzw. neue Fassung. Bei `replaces` wird die alte Fassung archiviert (nicht gelöscht:
    bereits freigegebene Schreiben stützen sich ggf. darauf) und aus der Suche genommen."""
    import re
    import shutil

    from .understand import documents

    old = store.get("documents", replaces) if replaces else None
    if replaces and (not old or old["project_id"] != LEGAL or old.get("collection") != "legal"):
        raise EditError("Zu ersetzende Rechtsgrundlage nicht gefunden")
    title = (title or "").strip() or (old["title"] if old else Path(path).stem)
    dest_dir = settings.data_dir() / LEGAL
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    dest = dest_dir / f"{stamp}_{Path(path).name}"
    shutil.copyfile(path, dest)
    parsed = documents.parse(dest)
    pages = [{**p, "text": _legal_sections(p["text"])} for p in parsed["pages"]]
    if not any(p["text"].strip() for p in pages) or parsed.get("backend") == "none":
        dest.unlink(missing_ok=True)
        raise EditError("Kein Text lesbar – bitte PDF mit Textebene, DOCX, TXT oder MD hochladen")
    slug = re.sub(r"[^A-Z0-9]+", "-", title.upper()).strip("-")[:40] or "TEXT"
    doc = {"doc_id": f"LEGAL-{slug}-{stamp}", "project_id": LEGAL, "title": title, "file": f"{LEGAL}/{dest.name}",
           "kind": "rechtsgrundlage", "collection": "legal", "pages": pages, "tables": [],
           "version": (version or "").strip() or None, "uploaded_at": store.now_iso(), "uploaded_by": actor,
           "replaces": replaces}
    store.save_document(doc)
    if old:
        old.update(collection="legal_archive", superseded_by=doc["doc_id"], superseded_at=store.now_iso())
        store.save_document(old)
    rag.index(rebuild=True)
    store.audit(actor, "document", doc["doc_id"], "legal_update" if old else "legal_add",
                before={"doc_id": replaces, "title": old["title"], "version": old.get("version")} if old else None,
                after={"title": title, "version": doc["version"], "file": doc["file"]})
    return doc


def archive_legal(doc_id: str, actor: str) -> dict:
    """Rechtsgrundlage aus der Suche nehmen (archivieren); Text bleibt für bestehende Schreiben erhalten."""
    d = store.get("documents", doc_id)
    if not d or d["project_id"] != LEGAL:
        raise EditError("Rechtsgrundlage nicht gefunden")
    if d.get("collection") == "legal_archive":
        d.update(collection="legal", superseded_by=None, superseded_at=None)  # wiederherstellen
        action = "legal_restore"
    else:
        d.update(collection="legal_archive", superseded_at=store.now_iso())
        action = "legal_archive"
    store.save_document(d)
    rag.index(rebuild=True)
    store.audit(actor, "document", doc_id, action, after={"title": d["title"]})
    return d
