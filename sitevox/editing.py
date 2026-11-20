"""Manuelle Bearbeitung und Löschung durch die Bauleitung.

Grundsätze
  * Jede Änderung geht ins Audit-Log (vorher/nachher).
  * Abgeleitete Werte (KPIs, Gantt, Prognose, Konfidenz) werden NICHT direkt editiert, sondern aus den
    bearbeiteten Eingaben neu berechnet (refresh_day).
  * Belege, die in einem freigegebenen/versendeten Schreiben stecken, dürfen nicht gelöscht werden
    (Nachweisfunktion). Entwürfe werden neu geprüft – fehlende Belege erscheinen dort rot.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Optional

from . import rag, settings, store
from .engine import schedule

LOCKED_LETTER = ("Geprüft", "Versendet")


class EditError(ValueError):
    pass


# ============================================================================ Projekt-Stammdaten
PROJECT_FIELDS = ("name", "title", "address", "contract_no", "contract_date", "contract_basis", "lat", "lon")
CLIENT_FIELDS = ("name", "address", "representative", "representative_role", "email")


def update_project(project_id: str, patch: dict, actor: str) -> dict:
    p = dict(settings.project_cfg(project_id))
    before = {k: p.get(k) for k in PROJECT_FIELDS} | {"client": dict(p.get("client", {}))}
    for k in PROJECT_FIELDS:
        if k in patch:
            p[k] = patch[k]
    if "client" in patch:
        p["client"] = {**p.get("client", {}), **{k: v for k, v in patch["client"].items() if k in CLIENT_FIELDS}}
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
    prev = [p for p in store.progress(project_id) if p["activity_id"] == activity_id and p["date"] == day]
    if qty is None:
        store.execute("DELETE FROM progress WHERE project_id=? AND activity_id=? AND date=?",
                      (project_id, activity_id, day))
    else:
        store.save_progress(project_id, activity_id, day, float(qty), prev[0]["evidence_id"] if prev else None)
    store.audit(actor, "progress", f"{project_id}/{activity_id}/{day}", "edit",
                before=prev[0]["qty"] if prev else None, after=qty, note="manuelle Korrektur Ist-Menge")


def set_staffing(project_id: str, day: str, crew: str, present: Optional[int], planned: Optional[int],
                 actor: str) -> None:
    prev = [s for s in store.staffing(project_id, day) if s["crew"] == crew]
    if present is None:
        store.execute("DELETE FROM staffing WHERE project_id=? AND date=? AND crew=?", (project_id, day, crew))
    else:
        store.save_staffing(project_id, day, crew, int(present), int(planned if planned is not None else present),
                            prev[0]["evidence_id"] if prev else None)
    store.audit(actor, "staffing", f"{project_id}/{day}/{crew}", "edit", before=prev[0] if prev else None,
                after={"present": present, "planned": planned})


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
def _purge_derived(cap: dict, actor: str, *, keep_source: bool) -> dict:
    """Entfernt alles, was aus einer Erfassung abgeleitet wurde. Gibt eine Zusammenfassung zurück."""
    from .drafting import composer

    evs = store.evidence_by_capture(cap["capture_id"])
    ids = {e["evidence_id"] for e in evs}
    source_id = cap["evidence_ids"][0] if cap.get("evidence_ids") else None
    remove = ids - ({source_id} if keep_source and source_id else set())

    for l in store.letters(cap["project_id"]):
        if l["status"] in LOCKED_LETTER and remove & set(l["evidence_map"].values()):
            raise EditError(f"Beleg wird in Schreiben {l['letter_id']} ({l['status']}) verwendet – "
                            "Löschen nicht zulässig (Nachweis)")
    summary = {"evidence": len(remove), "progress": 0, "staffing": 0, "events_deleted": [], "letters_rechecked": []}
    if remove:
        q = ",".join("?" * len(remove))
        summary["progress"] = store.execute(f"DELETE FROM progress WHERE evidence_id IN ({q})", list(remove))
        summary["staffing"] = store.execute(f"DELETE FROM staffing WHERE evidence_id IN ({q})", list(remove))
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
    if patch.get("reanalyze"):
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
