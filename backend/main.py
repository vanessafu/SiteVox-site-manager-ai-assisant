"""SiteVox API (FastAPI).

Start:  uvicorn backend.main:app --reload --port 8000     (aus dem Repo-Root)
Demo:   python scripts/make_demo_data.py && python scripts/seed_demo.py

Human-in-the-loop ist technisch erzwungen:
  * Es gibt keinen Endpunkt, der eine E-Mail versendet. "Freigeben" erzeugt nur DOCX/PDF/.eml-Entwurf,
    optional einen Outlook-Entwurf über Graph mit Mail.ReadWrite (ohne Mail.Send).
  * Freigabe nur, wenn alle roten Stellen bestätigt und die Checkliste vollständig ist.
  * "Versendet" setzt ausschließlich die Bauleitung, nachdem sie selbst gesendet hat.
"""
from __future__ import annotations

import sys
import mimetypes
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from sitevox import DISCLAIMER, editing, mail_accounts, pipeline, rag, settings, store  # noqa: E402
from sitevox.drafting import composer  # noqa: E402
from sitevox.understand import gaeb_io, imap_mail  # noqa: E402
from sitevox.export import daily_report as daily_report_export, docx_export, outlook  # noqa: E402

from . import views  # noqa: E402

app = FastAPI(title="SiteVox API", version="0.1.0",
              description="KI-Assistent für Bauleiter – Entwürfe, keine Rechtsberatung.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
ACTOR = "Bauleitung"  # Demo: ein Nutzer. Produktiv: aus Auth-Token.


def _letter(lid: str) -> dict:
    l = store.get("letters", lid)
    if not l:
        raise HTTPException(404, "Schreiben nicht gefunden")
    return l


# ------------------------------------------------------------------------------------------- meta
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "mode": settings.mode(), "disclaimer": DISCLAIMER}


@app.get("/api/projects")
def projects() -> list[dict]:
    return views.projects()


@app.get("/api/projects/{pid}/dashboard")
def dashboard(pid: str, date: Optional[str] = None) -> dict:
    return views.dashboard(pid, date or views.default_day(pid))


@app.get("/api/projects/{pid}/schedule")
def schedule(pid: str, date: Optional[str] = None) -> dict:
    d = views.dashboard(pid, date or views.default_day(pid))
    return {"date": d["date"], **d["overview"]}


# ------------------------------------------------------------------------------------------- captures
@app.get("/api/projects/{pid}/captures")
def captures(pid: str, date: Optional[str] = None) -> list[dict]:
    caps = store.captures(pid, date) if date else store.captures(pid)
    for c in caps:
        c.pop("text", None) if c["kind"] == "document" else None
    return caps


@app.get("/api/captures/{cid}")
def capture(cid: str) -> dict:
    c = store.get("captures", cid)
    if not c:
        raise HTTPException(404)
    c["evidence"] = store.evidence_many(c["evidence_ids"])
    return c


def _run_ingest(pid: str, kind: str, path: Optional[Path], text: Optional[str], captured_at: str, meta: dict,
                prefer_exif_time: bool = False, description: Optional[dict] = None) -> None:
    try:
        pipeline.ingest(pid, kind, file=path, text=text, captured_at=captured_at, meta=meta, actor=ACTOR,
                        prefer_exif_time=prefer_exif_time, description=description)
    except Exception as e:  # noqa: BLE001
        store.audit("system", "capture", pid, "ingest_failed", note=str(e))


async def _tmp_file(upload: UploadFile, default: str) -> Path:
    tmp = Path(tempfile.mkdtemp()) / Path(upload.filename or default).name
    tmp.write_bytes(await upload.read())
    return tmp


@app.post("/api/projects/{pid}/captures")
async def upload_capture(pid: str, background: BackgroundTasks, kind: str = Form(...),
                         text: Optional[str] = Form(None), captured_at: Optional[str] = Form(None),
                         transcript_hint: Optional[str] = Form(None), lat: Optional[float] = Form(None),
                         lon: Optional[float] = Form(None), language: Optional[str] = Form(None),
                         asr_language: Optional[str] = Form(None),
                         doc_type: Optional[str] = Form(None), doc_title: Optional[str] = Form(None),
                         description_mode: Optional[str] = Form(None), description_text: Optional[str] = Form(None),
                         description_audio: Optional[UploadFile] = File(None),
                         file: Optional[UploadFile] = File(None)) -> dict:
    """Mobile Erfassung: Audio (MediaRecorder), Foto, Notiz, .eml oder Dokument. Verarbeitung im Hintergrund."""
    if kind not in ("audio", "photo", "note", "email", "document"):
        raise HTTPException(400, "unbekannte Art")
    ts = captured_at or datetime.now().astimezone().isoformat(timespec="seconds")
    path = None
    if file is not None:
        path = await _tmp_file(file, f"upload_{kind}")
    elif kind != "note":
        raise HTTPException(400, "Datei fehlt")
    meta: dict[str, Any] = {"source": "mobile"}
    if transcript_hint:
        meta["transcript_hint"] = transcript_hint
    if doc_type:
        meta["doc_type"] = doc_type
    if doc_title:
        meta["doc_title"] = doc_title
    # `language` ist die UI-Sprache und erzwingt KEINE Whisper-Sprache mehr (türkisch sprechender Polier
    # mit deutscher UI). Standard: automatische Erkennung unter de/en/tr/pl; explizit nur via asr_language.
    if asr_language in ("de", "en", "tr", "pl", "auto"):
        meta["language"] = asr_language
    # UI-Sprache (de|en) bestimmt die Sprache der KI-Texte (Zusammenfassung, Rückfrage); Zitate bleiben im Original
    meta["output_language"] = settings.output_language(language)
    if lat is not None and lon is not None:
        meta["gps"] = {"lat": lat, "lon": lon}
    # Foto: Aufnahmezeit aus EXIF, sofern der Client keine Zeit mitschickt (Datum ← EXIF)
    # Foto + Beschreibung (Sprache oder Notiz) in einem Upload → keine KI-Rückfrage
    description = None
    if kind == "photo" and description_mode:
        if description_mode not in ("audio", "note", "none"):
            raise HTTPException(400, "description_mode muss audio, note oder none sein")
        if description_mode == "audio" and description_audio is None:
            raise HTTPException(400, "Sprachbeschreibung fehlt")
        if description_mode == "note" and not (description_text or "").strip():
            raise HTTPException(400, "Beschreibungstext fehlt")
        description = {"mode": description_mode, "text": description_text or transcript_hint,
                       "file": await _tmp_file(description_audio, "beschreibung.webm") if description_audio else None,
                       "language": meta.get("language")}
    background.add_task(_run_ingest, pid, kind, path, text, ts, meta, kind == "photo" and not captured_at,
                        description)
    return {"accepted": True, "captured_at": ts}


def _run_answer(cid: str, mode: str, text: Optional[str], path: Optional[Path], detail: Optional[Path],
                language: Optional[str]) -> None:
    try:
        pipeline.answer_photo(cid, mode, text=text, file=path, detail_photo=detail, language=language, actor=ACTOR)
    except Exception as e:  # noqa: BLE001
        store.audit("system", "capture", cid, "answer_failed", note=str(e))


@app.post("/api/captures/{cid}/answer")
async def answer_capture(cid: str, background: BackgroundTasks, mode: str = Form(...),
                         text: Optional[str] = Form(None), asr_language: Optional[str] = Form(None),
                         file: Optional[UploadFile] = File(None),
                         detail_photo: Optional[UploadFile] = File(None)) -> dict:
    """Antwort auf die Foto-Rückfrage: mode = audio (Sprachantwort, Whisper) | note (Text) | skip.
    Landet in derselben Erfassung; Extraktion + Regelwerk laufen im Hintergrund."""
    cap = store.get("captures", cid)
    if not cap or cap["kind"] != "photo":
        raise HTTPException(404, "Foto-Erfassung nicht gefunden")
    if mode not in ("audio", "note", "skip"):
        raise HTTPException(400, "mode muss audio, note oder skip sein")
    if cap["status"] == "processing":
        raise HTTPException(409, "Erfassung wird gerade verarbeitet")
    if mode == "audio" and file is None:
        raise HTTPException(400, "Audiodatei fehlt")
    if mode == "note" and not (text or "").strip():
        raise HTTPException(400, "Antworttext fehlt")
    path = await _tmp_file(file, "antwort.webm") if file is not None and mode == "audio" else None
    detail = await _tmp_file(detail_photo, "detail.jpg") if detail_photo is not None else None
    lang = asr_language if asr_language in ("de", "en", "tr", "pl", "auto") else None
    cap["status"] = "processing"  # sofort sichtbar, bevor der Hintergrundjob startet
    store.save_capture(cap)
    background.add_task(_run_answer, cid, mode, text, path, detail, lang)
    return {"accepted": True, "capture_id": cid}


# ------------------------------------------------------------------------------------------- events
@app.get("/api/projects/{pid}/events")
def events(pid: str, date: Optional[str] = None) -> list[dict]:
    return [views.event_card(e) for e in store.events(pid, date)]


@app.get("/api/events/{eid}")
def event(eid: str) -> dict:
    e = store.get("events", eid)
    if not e:
        raise HTTPException(404)
    card = views.event_card(e)
    card["evidence_docs"] = store.evidence_many(e["evidence"])
    card["field_confidence"] = e.get("confidence", {}).get("fields", {})
    card["audit"] = store.audit_log(eid)
    return card


class SphereIn(BaseModel):
    sphere: str


@app.post("/api/events/{eid}/sphere")
def confirm_sphere(eid: str, body: SphereIn) -> dict:
    if body.sphere not in ("AG", "AN", "neutral"):
        raise HTTPException(400)
    return views.event_card(pipeline.confirm_sphere(eid, body.sphere, ACTOR))


@app.post("/api/events/{eid}/sphere/reset")
def reset_sphere(eid: str) -> dict:
    """Bestätigte Sphäre zurücksetzen → wieder Regel-Vorschlag."""
    if not store.get("events", eid):
        raise HTTPException(404)
    return views.event_card(pipeline.reset_sphere(eid, ACTOR))


class NoteIn(BaseModel):
    note: str = ""


@app.post("/api/events/{eid}/dismiss")
def dismiss(eid: str, body: NoteIn) -> dict:
    return views.event_card(pipeline.dismiss_event(eid, ACTOR, body.note))


@app.post("/api/events/{eid}/draft")
def create_draft(eid: str, body: Optional[dict] = Body(None)) -> dict:
    """body.language (de|en) = UI-Sprache → Sprache des Schreibens (Vorlage + KI-Sätze)."""
    e = store.get("events", eid)
    if not e:
        raise HTTPException(404)
    if e.get("letter_id"):
        return views.letter_view(_letter(e["letter_id"]))
    try:
        return views.letter_view(composer.create_letter(
            eid, actor=ACTOR, language=settings.output_language((body or {}).get("language"))))
    except ValueError as ex:
        raise HTTPException(409, str(ex)) from ex


# ------------------------------------------------------------------------------------------- letters
@app.get("/api/projects/{pid}/letters")
def letters(pid: str) -> list[dict]:
    out = []
    for l in store.letters(pid):
        l = composer.ensure_recipient_email(l)
        ev = store.get("events", l["event_id"]) or {}
        fe = l["fields"].get("recipient_email") or {}
        out.append({"letter_id": l["letter_id"], "kind": l["kind"], "kind_label": views.DOC_KIND_LABELS[l["kind"]],
                    "status": l["status"], "event_id": l["event_id"], "event_label": ev.get("label"),
                    "betreff": next((s["text"] for s in l.get("rendered", []) if s["key"] == "betreff"), ""),
                    "created_at": l["created_at"], "sent_at": l.get("sent_at"),
                    "open_issues": len([i for i in l["issues"] if i["status"] in ("unverified", "needs_confirmation")]),
                    "deadline": views.event_card(ev)["deadline"] if ev else None,
                    "recipient_email": fe.get("value"), "recipient_email_status": fe.get("status")})
    return out


@app.get("/api/letters/{lid}")
def letter(lid: str) -> dict:
    return views.letter_view(_letter(lid))


class FieldAction(BaseModel):
    action: str  # accept | edit | reject
    value: Any = None


@app.post("/api/letters/{lid}/fields/accept-all")
def fields_accept_all(lid: str) -> dict:
    """Alle offenen Felder übernehmen (vor der generischen /fields/{key}-Route registriert)."""
    try:
        return views.letter_view(composer.accept_all_fields(lid, ACTOR))
    except ValueError as ex:
        raise HTTPException(400, str(ex)) from ex


@app.post("/api/letters/{lid}/fields/{key}")
def field_action(lid: str, key: str, body: FieldAction) -> dict:
    try:
        return views.letter_view(composer.field_action(lid, key, body.action, ACTOR, body.value))
    except (ValueError, KeyError) as ex:
        raise HTTPException(400, str(ex)) from ex


class SentenceIn(BaseModel):
    text: str
    evidence: Optional[list[str]] = None


@app.put("/api/letters/{lid}/sentences/{section}/{idx}")
def edit_sentence(lid: str, section: str, idx: int, body: SentenceIn) -> dict:
    return views.letter_view(composer.edit_sentence(lid, section, idx, body.text, ACTOR, body.evidence))


@app.post("/api/letters/{lid}/issues/{iid}/confirm")
def confirm_issue(lid: str, iid: str, body: NoteIn) -> dict:
    return views.letter_view(composer.confirm_issue(lid, iid, ACTOR, body.note))


class CheckIn(BaseModel):
    value: bool


@app.post("/api/letters/{lid}/checklist/{key}")
def checklist(lid: str, key: str, body: CheckIn) -> dict:
    return views.letter_view(composer.set_checklist(lid, key, body.value, ACTOR))


@app.post("/api/letters/{lid}/release")
def release(lid: str) -> dict:
    """Freigeben – erzeugt Exporte. Sendet nichts."""
    try:
        return views.letter_view(composer.release(lid, ACTOR))
    except PermissionError as ex:
        raise HTTPException(409, {"blockers": str(ex).split("; ")}) from ex


@app.post("/api/letters/{lid}/revoke")
def revoke(lid: str, body: NoteIn) -> dict:
    """Eine Stufe zurück: Versendet → Geprüft bzw. Geprüft → Entwurf (Begründung Pflicht, Audit-Log)."""
    try:
        return views.letter_view(composer.revoke(lid, ACTOR, body.note))
    except ValueError as ex:
        raise HTTPException(409, str(ex)) from ex


@app.post("/api/letters/{lid}/reject")
def reject(lid: str, body: NoteIn) -> dict:
    return views.letter_view(composer.reject_letter(lid, ACTOR, body.note))


class SentIn(BaseModel):
    method: str = "E-Mail + Einschreiben"


@app.post("/api/letters/{lid}/mark-sent")
def mark_sent(lid: str, body: SentIn) -> dict:
    try:
        return views.letter_view(composer.mark_sent(lid, ACTOR, body.method))
    except ValueError as ex:
        raise HTTPException(409, str(ex)) from ex


class GraphIn(BaseModel):
    access_token: str


@app.get("/api/letters/{lid}/send-preview")
def letter_send_preview(lid: str) -> dict:
    _letter(lid)
    return composer.send_preview(lid)


@app.post("/api/letters/{lid}/send-email")
def letter_send_email(lid: str, body: dict) -> dict:
    """Nur nach Bestätigung im Sendedialog; Freigabe allein sendet nie."""
    _letter(lid)
    if not body.get("confirm"):
        raise HTTPException(400, "Versand muss im Dialog bestätigt werden")
    try:
        if body.get("to") and body["to"].strip() != composer.recipient_email(_letter(lid)):
            composer.set_recipient_email(lid, body["to"], ACTOR)  # im Dialog geänderter Empfänger (Audit-Log)
        composer.send_email(lid, body.get("account_id") or "", body.get("cc") or [], ACTOR)
    except KeyError as e:
        raise HTTPException(404, "Postfach nicht gefunden") from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    except imap_mail.MailError as e:
        raise HTTPException(502, str(e)) from e
    return views.letter_view(store.get("letters", lid))


@app.put("/api/letters/{lid}/recipient-email")
def letter_recipient_email(lid: str, body: dict) -> dict:
    _letter(lid)
    try:
        composer.set_recipient_email(lid, body.get("value") or "", ACTOR)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return views.letter_view(store.get("letters", lid))


@app.post("/api/letters/{lid}/original-sent")
def letter_original_sent(lid: str, body: dict) -> dict:
    _letter(lid)
    try:
        composer.original_sent(lid, ACTOR, body.get("method") or "Einschreiben mit Rückschein")
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return views.letter_view(store.get("letters", lid))


@app.post("/api/letters/{lid}/outlook-draft")
def outlook_draft(lid: str, body: GraphIn) -> dict:
    """Optional: Entwurf im Outlook-Postfach anlegen (Graph, Mail.ReadWrite). Kein Versand."""
    l = _letter(lid)
    if l["status"] != "Geprüft":
        raise HTTPException(409, "Erst freigeben")
    res = outlook.graph_create_draft(l, body.access_token, Path(l["exports"]["docx"]))
    store.audit(ACTOR, "letter", lid, "outlook_draft", after=res)
    return res


@app.get("/api/letters/{lid}/export/{fmt}")
def export(lid: str, fmt: str) -> FileResponse:
    l = _letter(lid)
    if l["status"] not in ("Geprüft", "Versendet"):
        raise HTTPException(409, "Export erst nach Freigabe (alle roten Stellen bestätigt, Checkliste erfüllt)")
    p = l["exports"].get(fmt)
    if not p or not Path(p).exists():
        raise HTTPException(404, f"{fmt} nicht vorhanden" + (" – LibreOffice nicht installiert" if fmt == "pdf" else ""))
    store.audit(ACTOR, "letter", lid, f"download_{fmt}")
    media = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "pdf": "application/pdf", "eml": "message/rfc822"}[fmt]
    return FileResponse(p, media_type=media, filename=Path(p).name)


@app.get("/api/projects/{pid}/report")
def report_sections(pid: str, date: Optional[str] = None) -> dict:
    """Abschnitte des Bautagesberichts als JSON fürs Dashboard – dieselbe Funktion wie PDF/DOCX."""
    if pid not in {p["id"] for p in store.list_projects()}:
        raise HTTPException(404, "Projekt unbekannt")
    return views.report_sections(pid, date or views.default_day(pid))


@app.get("/api/projects/{pid}/daily-report")
def daily_report(pid: str, date: Optional[str] = None, fmt: str = "pdf") -> FileResponse:
    """Bautagesbericht als PDF, DOCX (gleiches Layout) oder JSON (Rohdaten)."""
    if fmt not in ("pdf", "docx", "json"):
        raise HTTPException(400, "fmt muss pdf, docx oder json sein")
    paths = daily_report_export.export_files(pid, date or views.default_day(pid))
    p = paths[fmt]
    store.audit(ACTOR, "export", pid, "daily_report", after=paths)
    media = {"pdf": "application/pdf", "json": "application/json",
             "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[fmt]
    return FileResponse(p, media_type=media, filename=Path(p).name)


# ------------------------------------------------------------------------------------------- mailbox / KB
@app.get("/api/projects/{pid}/mailbox")
def mailbox(pid: str) -> list[dict]:
    out = []
    for m in store.emails(pid):
        cap = store.get("captures", m.get("capture_id")) if m.get("capture_id") else None
        out.append({**m, "summary": cap.get("summary") if cap else None,
                    "event_ids": cap.get("event_ids", []) if cap else []})
    return out


@app.get("/api/mail-providers")
def mail_providers() -> dict:
    return imap_mail.PRESETS


@app.get("/api/projects/{pid}/mail-accounts")
def mail_account_list(pid: str) -> list[dict]:
    return mail_accounts.accounts(pid)


@app.post("/api/projects/{pid}/mail-accounts")
def mail_account_add(pid: str, body: dict) -> dict:
    try:
        return mail_accounts.add(pid, body, ACTOR)
    except imap_mail.MailError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/projects/{pid}/mail-accounts/{aid}/unlock")
def mail_account_unlock(pid: str, aid: str, body: dict) -> dict:
    try:
        return mail_accounts.unlock(pid, aid, body.get("password") or "")
    except KeyError as e:
        raise HTTPException(404) from e
    except imap_mail.MailError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/projects/{pid}/mail-accounts/{aid}")
def mail_account_remove(pid: str, aid: str) -> dict:
    try:
        mail_accounts.remove(pid, aid, ACTOR)
    except KeyError as e:
        raise HTTPException(404) from e
    return {"ok": True}


@app.post("/api/projects/{pid}/mail-accounts/{aid}/sync")
def mail_account_sync(pid: str, aid: str, background: BackgroundTasks) -> dict:
    def ingest(path: Path, received_at: str) -> None:
        background.add_task(_run_ingest, pid, "email", path, None, received_at, {"source": "imap"})

    try:
        return mail_accounts.sync(pid, aid, ingest, ACTOR)
    except KeyError as e:
        raise HTTPException(404) from e
    except PermissionError as e:
        raise HTTPException(409, str(e)) from e
    except imap_mail.MailError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/projects/{pid}/knowledge")
def knowledge(pid: str) -> list[dict]:
    return [{"doc_id": d["doc_id"], "title": d["title"], "kind": d.get("kind"), "collection": d.get("collection"),
             "project_id": d["project_id"], "pages": len(d["pages"]), "file": d.get("file"),
             "format": "gaeb" if d.get("gaeb") else None}
            for d in store.documents(pid)]


@app.get("/api/documents/{doc_id}")
def document(doc_id: str) -> dict:
    d = store.get("documents", doc_id)
    if not d:
        raise HTTPException(404)
    d["gaeb_exportable"] = d.get("collection") == "project" and bool(gaeb_io.doc_items(d))
    return d


@app.get("/api/documents/{doc_id}/gaeb")
def document_gaeb(doc_id: str, phase: str = "83") -> FileResponse:
    """LV → GAEB DA XML 3.3 (Phase 81/83/84/86), z. B. für Nachträge/Angebote an AVA-Software des AG."""
    d = store.get("documents", doc_id)
    if not d:
        raise HTTPException(404)
    if d.get("collection") != "project" or not gaeb_io.doc_items(d):
        raise HTTPException(400, "Dokument enthält keine LV-Positionen (Tabelle mit Pos./Kurztext/Menge/Einheit)")
    try:
        p = gaeb_io.export(d, settings.data_dir() / d["project_id"] / "exports", phase=phase,
                           project=settings.project_cfg(d["project_id"]), company=settings.baseline().get("company"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    store.audit(ACTOR, "document", doc_id, "gaeb_export", after={"phase": phase, "file": p.name})
    return FileResponse(p, media_type="application/xml", filename=p.name)


@app.get("/api/evidence-sources")
def evidence_sources(ids: str) -> list[dict]:
    """Belege nach Quelle gruppiert: eine Sprachnachricht/ein Foto/eine Mail/ein Dokument erscheint nur einmal,
    mit allen Fundstellen (Audio-Abschnitte, Bildausschnitte, Zitate) zum Hervorheben."""
    return views.evidence_sources([i for i in ids.split(",") if i])


@app.get("/api/projects/{pid}/knowledge/search")
def knowledge_search(pid: str, q: str, collection: Optional[str] = None) -> list[dict]:
    return [{k: (float(v) if hasattr(v, "item") else v) for k, v in h.items()}
            for h in rag.index().search(q, project_id=pid, collection=collection, k=6)]


@app.get("/api/evidence/{evid}")
def evidence(evid: str) -> dict:
    e = store.evidence(evid)
    if not e:
        raise HTTPException(404)
    if e.get("capture_id"):
        cap = store.get("captures", e["capture_id"]) or {}
        e["transcript"] = cap.get("transcript")
        e["email"] = cap.get("email")
    return e


class ReviewIn(BaseModel):
    action: str  # confirm | reject | reset
    note: str = ""


@app.post("/api/evidence/{evid}/review")
def review_evidence(evid: str, body: ReviewIn) -> dict:
    """KI-Beobachtung bestätigen (→ zählt als Beleg), verwerfen oder zurücksetzen. Audit-Log."""
    try:
        return pipeline.review_ai_observation(evid, body.action, ACTOR, body.note)
    except ValueError as ex:
        raise HTTPException(400, str(ex)) from ex


@app.get("/api/audit")
def audit(entity_id: Optional[str] = None) -> list[dict]:
    return store.audit_log(entity_id)


# ------------------------------------------------------------------------------------------- Bearbeiten / Löschen
def _edit(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except editing.EditError as ex:
        raise HTTPException(409, str(ex)) from ex
    except (ValueError, KeyError) as ex:
        raise HTTPException(400, str(ex)) from ex


@app.get("/api/projects/{pid}/master")
def project_master(pid: str) -> dict:
    return settings.project_cfg(pid)


@app.put("/api/projects/{pid}/master")
def update_project(pid: str, body: dict) -> dict:
    return _edit(editing.update_project, pid, body, ACTOR)


@app.get("/api/projects/{pid}/activities")
def activities(pid: str) -> list[dict]:
    return store.activities(pid)


@app.post("/api/projects/{pid}/activities")
def create_activity(pid: str, body: dict) -> dict:
    return _edit(editing.save_activity, pid, None, body, ACTOR)


@app.put("/api/projects/{pid}/activities/{aid}")
def update_activity(pid: str, aid: str, body: dict) -> dict:
    return _edit(editing.save_activity, pid, aid, body, ACTOR)


@app.delete("/api/projects/{pid}/activities/{aid}")
def delete_activity(pid: str, aid: str) -> dict:
    _edit(editing.delete_activity, pid, aid, ACTOR)
    return {"deleted": aid}


class ProgressIn(BaseModel):
    activity_id: str
    date: str
    qty: Optional[float] = None  # None = Eintrag löschen


@app.put("/api/projects/{pid}/progress")
def set_progress(pid: str, body: ProgressIn) -> dict:
    _edit(editing.set_progress, pid, body.activity_id, body.date, body.qty, ACTOR)
    pipeline.refresh_day(pid, datetime.fromisoformat(body.date).date())
    return {"ok": True}


@app.get("/api/projects/{pid}/progress")
def get_progress(pid: str, date: Optional[str] = None) -> list[dict]:
    return [p for p in store.progress(pid) if not date or p["date"] == date]


class StaffIn(BaseModel):
    date: str
    crew: str
    present: Optional[int] = None
    planned: Optional[int] = None


@app.put("/api/projects/{pid}/staffing")
def set_staffing(pid: str, body: StaffIn) -> dict:
    _edit(editing.set_staffing, pid, body.date, body.crew, body.present, body.planned, ACTOR)
    return {"ok": True}


class ReportRowIn(BaseModel):
    date: str
    section: str  # workforce | equipment
    key: str  # Kolonne bzw. Gerät
    action: str = "set"  # set | delete | reset
    data: Optional[dict] = None


@app.put("/api/projects/{pid}/report-rows")
def set_report_row(pid: str, body: ReportRowIn) -> dict:
    _edit(editing.set_report_row, pid, body.date, body.section, body.key, body.data, body.action, ACTOR)
    return {"ok": True}


@app.patch("/api/events/{eid}")
def update_event(eid: str, body: dict) -> dict:
    return views.event_card(_edit(editing.update_event, eid, body, ACTOR))


@app.delete("/api/events/{eid}")
def delete_event(eid: str) -> dict:
    _edit(editing.delete_event, eid, ACTOR)
    return {"deleted": eid}


@app.patch("/api/captures/{cid}")
def update_capture(cid: str, body: dict) -> dict:
    return _edit(editing.update_capture, cid, body, ACTOR)


@app.delete("/api/captures/{cid}")
def delete_capture(cid: str) -> dict:
    return _edit(editing.delete_capture, cid, ACTOR)


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str) -> dict:
    _edit(editing.delete_document, doc_id, ACTOR)
    return {"deleted": doc_id}


# Python kennt .m4a als "audio/mp4a-latm" – Safari spielt das nicht; Standard ist audio/mp4
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/webm", ".webm")


@app.get("/files/{path:path}")
def files(path: str) -> FileResponse:
    base = settings.data_dir().resolve()
    p = (base / path).resolve()
    if not str(p).startswith(str(base)) or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)
