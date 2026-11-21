"""Tests der deterministischen Kernlogik + End-to-End-Demo-Lauf (Demo-Modus, keine GPU)."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def demo_db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sitevox")
    os.environ["SITEVOX_MODE"] = "demo"
    os.environ["SITEVOX_DB"] = str(tmp / "test.db")
    os.environ["SITEVOX_DATA"] = str(tmp / "data")
    os.environ["SITEVOX_OCR"] = "0"  # OCR separat getestet (test_ocr_image_text), Seed bleibt schnell
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_demo_data.py")], check=True, capture_output=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_demo.py")], check=True, capture_output=True,
                   env=os.environ.copy())
    yield


# ----------------------------------------------------------------------------- engine
def test_calendar_and_cpm():
    from sitevox.engine.schedule import WorkCalendar, cpm, parse_preds

    cal = WorkCalendar(date(2026, 11, 2))
    assert cal.index(date(2026, 11, 20)) == 15
    assert cal.date_of(33) == date(2026, 12, 16)
    assert parse_preds("A40FS-1; A30SS+4") == [{"id": "A40", "type": "FS", "lag": -1},
                                               {"id": "A30", "type": "SS", "lag": 4}]
    acts = [
        {"id": "A", "name": "A", "duration": 3, "preds": [], "kind": "task", "start": "2026-11-02", "finish": "2026-11-04"},
        {"id": "B", "name": "B", "duration": 2, "preds": [{"id": "A", "type": "FS", "lag": 0}], "kind": "task",
         "start": "2026-11-05", "finish": "2026-11-06"},
        {"id": "M", "name": "M", "duration": 0, "preds": [{"id": "B", "type": "FS", "lag": 0}], "kind": "milestone",
         "start": "2026-11-09", "finish": "2026-11-09"},
    ]
    n = cpm(acts, cal)
    assert (n["B"].es, n["B"].ef) == (4, 5)
    assert n["B"].finish_float == 1  # Meilenstein am AT 6


def test_demo_deviation_numbers():
    from sitevox.engine import deviation

    a = deviation.analyze("BV-RIEM", date(2026, 11, 20))
    rows = {r["id"]: r for r in a["activities"]}
    assert rows["A40"]["delay_days"] == 2 and rows["A40"]["critical"]
    assert rows["A20"]["today"]["ratio"] == pytest.approx(190 / 320, abs=1e-3)
    assert not rows["A20"]["critical"]  # Bagger-Ausfall: Verzug, aber Puffer
    assert rows["A30"]["today"]["ratio"] == pytest.approx(1.05)
    assert a["kpis"]["next_deadline"]["overrun_days"] == 2
    assert a["impact"][0]["text"].startswith("Bewehrung BP +2 AT")
    assert "18.12." in a["impact"][0]["text"]


# ----------------------------------------------------------------------------- sphere
@pytest.mark.parametrize("typ,attrs,wx,sphere,doc", [
    ("equipment_failure", {}, None, "AN", "bautagebuch"),
    ("worker_shortage", {}, None, "AN", "interne_warnung"),
    ("planlieferverzug", {}, None, "AG", "behinderungsanzeige"),
    ("additional_work", {}, None, "AG", "mehrkostenankuendigung"),
    ("leistungsaenderung", {}, None, "AG", "nachtragsankuendigung"),
    ("weather_interruption", {}, False, "AN", "bautagebuch"),
    ("weather_interruption", {}, True, "neutral", "behinderungsanzeige"),
    ("material_delay", {"owner_supplied_material": True}, None, "AG", "behinderungsanzeige"),
    ("material_delay", {}, None, "AN", "bautagebuch"),
    ("quality_defect", {"own_work": False}, None, "AG", "bedenkenanzeige"),
    ("design_error", {}, None, "AG", "bedenkenanzeige"),
])
def test_sphere_rules(typ, attrs, wx, sphere, doc):
    from sitevox.engine import sphere as sph

    s, _ = sph.rule_sphere(typ, attrs, wx)
    assert s == sphere
    assert sph.recommend(typ, s, attrs, affects_schedule=True).kind == doc


def test_deadline_additional_work_started_is_critical():
    from sitevox.engine import deadlines

    st = deadlines.status("mehrkostenankuendigung", "2026-11-20T11:02:00+01:00", work_started=True)
    assert st["level"] == "critical"


# ----------------------------------------------------------------------------- confidence
def test_confidence_no_evidence_is_red():
    from sitevox import confidence as conf

    assert conf.combine(n_evidence=0, consistency=1.0)["band"] == "red"
    ok = conf.combine(n_evidence=2, asr=0.95, consistency=1.0, rule_ok=True)
    bad = conf.combine(n_evidence=2, asr=0.95, consistency=1.0, rule_ok=False)
    assert ok["band"] == "green" and bad["value"] < ok["value"] * 0.7
    assert conf.agreement([2, 2, 1, 3, 2]) == (2, 0.6)


# ----------------------------------------------------------------------------- verification
def test_verify_flags_unsupported_facts():
    from sitevox.verify import verify_sentences

    ev = {"EV-1": {"quote": "Der Bagger steht seit 10 Uhr. Aushub etwa 190 Kubik.", "captured_at":
                   "2026-11-20T10:02:00+01:00"}}
    issues = verify_sentences(
        {"sachverhalt": [
            {"text": "Am 20.11.2026 stand der Bagger ab 10:00 Uhr still.", "evidence": ["E-01"]},
            {"text": "Es wurden 250 m³ ausgehoben.", "evidence": ["E-01"]},
            {"text": "Gemäß § 6 VOB/B zeigen wir an.", "evidence": ["E-01"]},
            {"text": "Die Firma Huber GmbH war vor Ort.", "evidence": []},
        ]}, {"E-01": "EV-1"}, ev)
    bad = {(i.kind, i.value) for i in issues if i.status == "unverified"}
    assert ("number", "250") in bad
    assert any(k == "legal_ref" for k, _ in bad)
    assert any(k == "uncited" for k, _ in bad)
    assert any(k == "entity" and "Huber" in v for k, v in bad)
    good = {(i.kind, i.value) for i in issues if i.status == "verified"}
    assert ("time", "10:00") in good and ("date", "20.11.2026") in good


def test_quote_location_in_transcript():
    from sitevox.understand.asr import locate_quote

    tr = {"segments": [{"words": [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4, "score": 0.9}
                                  for i, w in enumerate("Der Bagger steht seit 10 Uhr kaputt".split())]}]}
    loc = locate_quote(tr, "Bagger steht seit 10 Uhr")
    assert loc and loc["t_start"] == 0.5 and loc["asr_score"] == 0.9


# ----------------------------------------------------------------------------- end-to-end HITL
def test_release_requires_human_and_never_sends():
    from fastapi.testclient import TestClient

    from backend.main import app

    c = TestClient(app)
    letters = {l["kind"]: l for l in c.get("/api/projects/BV-RIEM/letters").json()}
    lid = letters["behinderungsanzeige"]["letter_id"]
    v = c.get(f"/api/letters/{lid}").json()
    assert any("16.11.2026" in b for b in v["blockers"])  # bewusst unbelegtes Datum im Demo-Entwurf
    assert c.post(f"/api/letters/{lid}/release").status_code == 409
    assert c.get(f"/api/letters/{lid}/export/docx").status_code == 409
    for i in v["issues"]:
        if i["status"] == "unverified":
            c.post(f"/api/letters/{lid}/issues/{i['issue_id']}/confirm", json={"note": "Telefonnotiz"})
    for k in v["checklist"]:
        c.post(f"/api/letters/{lid}/checklist/{k}", json={"value": True})
    r = c.post(f"/api/letters/{lid}/release").json()
    assert r["status"] == "Geprüft"  # nicht "Versendet" – Versand macht nur der Mensch
    eml = c.get(f"/api/letters/{lid}/export/eml").content
    assert b"X-Unsent: 1" in eml
    routes = {getattr(r, "path", "") for r in app.routes}
    assert not any("send" in p and "mark-sent" not in p for p in routes)


# ----------------------------------------------------------------------------- Bearbeiten / Löschen
def test_edit_inputs_recompute_and_delete_capture():
    from fastapi.testclient import TestClient

    from backend.main import app

    c = TestClient(app)
    # Ist-Menge korrigieren → Soll-Ist neu berechnet
    c.put("/api/projects/BV-RIEM/progress", json={"activity_id": "A20", "date": "2026-11-20", "qty": 320})
    d = c.get("/api/projects/BV-RIEM/dashboard", params={"date": "2026-11-20"}).json()
    assert next(b for b in d["today"]["bullets"] if b["id"] == "A20")["ratio"] == 1.0
    # Vorgang bearbeiten, Zyklus abweisen
    r = c.put("/api/projects/BV-RIEM/activities/A60", json={"finish": "2026-12-15"})
    assert r.status_code == 200 and r.json()["duration"] == 12
    assert c.put("/api/projects/BV-RIEM/activities/A20", json={"preds": "A60FS+0"}).status_code == 409
    # Stammdaten
    r = c.put("/api/projects/BV-RIEM/master", json={"contract_no": "RI-2026-099"})
    assert c.get("/api/projects/BV-RIEM/master").json()["contract_no"] == "RI-2026-099"
    # Ereignis bearbeiten
    ev = [e for e in c.get("/api/projects/BV-RIEM/events", params={"date": "2026-11-20"}).json()
          if e["type"] == "equipment_failure"][0]
    r = c.patch(f"/api/events/{ev['event_id']}", json={"cause": "Hydraulikschlauch (korrigiert)"})
    assert r.json()["cause"] == "Hydraulikschlauch (korrigiert)"
    # Erfassung mit Beleg in freigegebenem Schreiben ist geschützt (siehe HITL-Test oben: DOC behinderung released)
    caps = c.get("/api/projects/BV-RIEM/captures", params={"date": "2026-11-20"}).json()
    rec0730 = next(x for x in caps if x["title"] == "Sprachmemo 07:30")
    assert c.delete(f"/api/captures/{rec0730['capture_id']}").status_code == 409
    # Bagger-Foto löschen: Ereignis bleibt (andere Belege), Datei weg
    photo = next(x for x in caps if x["kind"] == "photo" and "Bagger" in x["title"])
    r = c.delete(f"/api/captures/{photo['capture_id']}")
    assert r.status_code == 200 and r.json().get("file_deleted")
    assert c.get(f"/api/events/{ev['event_id']}").status_code == 200
    # Notiz anlegen, Text korrigieren und neu analysieren
    r = c.post("/api/projects/BV-RIEM/captures", data={"kind": "note", "text": "Alles ruhig.",
                                                        "captured_at": "2026-11-20T15:00:00+01:00"})
    note = [x for x in c.get("/api/projects/BV-RIEM/captures", params={"date": "2026-11-20"}).json()
            if x["kind"] == "note"][-1]
    r = c.patch(f"/api/captures/{note['capture_id']}",
                json={"text": "Kran steht seit 15 Uhr, Seilwinde defekt.", "reanalyze": True})
    assert r.json()["event_ids"]
    assert c.delete(f"/api/captures/{note['capture_id']}").status_code == 200
    assert any(a["action"] == "delete" for a in c.get("/api/audit").json())


def test_accept_all_fields_keeps_decisions_and_gates():
    from fastapi.testclient import TestClient

    from backend.main import app

    c = TestClient(app)
    lid = {l["kind"]: l for l in c.get("/api/projects/BV-RIEM/letters").json()}["mehrkostenankuendigung"]["letter_id"]
    c.post(f"/api/letters/{lid}/fields/delivery_method", json={"action": "reject"})
    v = c.post(f"/api/letters/{lid}/fields/accept-all").json()
    status = {f["key"]: f["status"] for f in v["fields"]}
    assert status.pop("delivery_method") == "rejected"  # bewusste Entscheidung bleibt
    assert set(status.values()) == {"accepted"}
    assert v["status"] == "Entwurf" and any(b.startswith("Checkliste") for b in v["blockers"])  # kein Freigabe-Bypass
    assert c.post(f"/api/letters/{lid}/release").status_code == 409


def test_revoke_steps_back_with_reason():
    """Läuft nach test_release_requires_human_and_never_sends (Behinderungsanzeige ist dann „Geprüft“)."""
    from fastapi.testclient import TestClient

    from backend.main import app

    c = TestClient(app)
    lid = {l["kind"]: l for l in c.get("/api/projects/BV-RIEM/letters").json()}["behinderungsanzeige"]["letter_id"]
    assert c.get(f"/api/letters/{lid}").json()["status"] == "Geprüft"
    assert c.post(f"/api/letters/{lid}/mark-sent", json={"method": "Einschreiben"}).json()["status"] == "Versendet"
    assert c.post(f"/api/letters/{lid}/revoke", json={"note": ""}).status_code == 409  # Begründung Pflicht
    assert c.post(f"/api/letters/{lid}/revoke", json={"note": "falsch markiert"}).json()["status"] == "Geprüft"
    v = c.post(f"/api/letters/{lid}/revoke", json={"note": "Anlage fehlt"}).json()
    assert v["status"] == "Entwurf" and v["released_at"] is None
    assert c.get(f"/api/letters/{lid}/export/docx").status_code == 409  # Downloads wieder gesperrt
    assert {"revoke_sent", "revoke_release"} <= {a["action"] for a in c.get("/api/audit").json()}
    assert c.post(f"/api/letters/{lid}/release").json()["status"] == "Geprüft"  # Entscheidungen bleiben erhalten
    # Verworfen → wiederherstellen → erneut freigeben
    c.post(f"/api/letters/{lid}/revoke", json={"note": "Korrektur"})
    assert c.post(f"/api/letters/{lid}/reject", json={"note": ""}).json()["status"] == "Verworfen"
    assert c.post(f"/api/letters/{lid}/revoke", json={"note": "doch nötig"}).json()["status"] == "Entwurf"
    assert c.post(f"/api/letters/{lid}/release").json()["status"] == "Geprüft"


def test_sphere_reset_returns_to_rule_suggestion():
    from fastapi.testclient import TestClient

    from backend.main import app

    c = TestClient(app)
    ev = next(e for e in c.get("/api/projects/BV-RIEM/events").json() if e["type"] == "worker_shortage")
    assert ev["sphere"] == "AN" and not ev["sphere_confirmed"]
    r = c.post(f"/api/events/{ev['event_id']}/sphere", json={"sphere": "AG"}).json()
    assert r["sphere"] == "AG" and r["sphere_confirmed"]
    r = c.post(f"/api/events/{ev['event_id']}/sphere/reset").json()
    assert r["sphere"] == "AN" and not r["sphere_confirmed"]  # wieder Regel-Vorschlag
    assert any(a["action"] == "reset_sphere" for a in c.get("/api/audit").json())


# ----------------------------------------------------------------------------- Foto: sehen → fragen → verstehen
def test_photo_analysis_schema_is_lenient_on_bbox_and_conf():
    from sitevox.schemas import PhotoAnalysis

    a = PhotoAnalysis.model_validate({"observations": [
        {"category": "defect", "subtype": "crack", "description": "Riss", "bbox": [900, 100, 100, 50],
         "visual_conf": 1.7},
        {"category": "obstruction", "subtype": "standing_water", "description": "Wasser", "bbox": [1, 2, 3],
         "visual_conf": "x"}]})
    assert a.observations[0].bbox == [100, 50, 900, 100] and a.observations[0].visual_conf == 1.0
    assert a.observations[1].bbox is None and a.observations[1].visual_conf == 0.5


def test_followup_prefers_p0_and_asks_what_rules_need():
    from sitevox.understand import vision

    an = {"observations": [
        {"category": "progress", "subtype": "stage_change", "description": "", "severity": "high", "visual_conf": .9},
        {"category": "defect", "subtype": "crack", "description": "", "severity": "medium", "visual_conf": .6}]}
    f = vision.followup(an)
    assert f["subtype"] == "crack" and "Vorleistung" in f["question"] and f["wants_detail_photo"]
    assert vision.followup({"observations": []})["question"] == "Was ist hier passiert?"


def test_verify_ai_observation_is_not_evidence_until_promoted():
    from sitevox.verify import blocking, verify_sentences

    ai = {"source": "ai_vision", "quote": "Riss am Wandfuß, etwa 40 cm lang.", "meta": {"status": "ai"}}
    sec = {"sachverhalt": [{"text": "Am Wandfuß ist ein Riss von 40 cm Länge sichtbar.", "evidence": ["E-01"]}]}
    issues = verify_sentences(sec, {"E-01": "EV-AI"}, {"EV-AI": ai})
    kinds = {(i.kind, i.status) for i in issues}
    assert ("ai_only", "needs_confirmation") in kinds and ("number", "unverified") in kinds
    assert len(blocking(issues)) == 2  # gelb und rot sperren die Freigabe
    ai["meta"]["status"] = "corroborated"  # Sprachantwort stützt die Beobachtung → Beleg
    issues = verify_sentences(sec, {"E-01": "EV-AI"}, {"EV-AI": ai})
    assert not blocking(issues)


def _demo_jpg(tmp_path, name: str):
    from PIL import Image

    p = tmp_path / name
    Image.new("RGB", (800, 600), (150, 150, 150)).save(p, quality=80)
    return p


def test_photo_defect_answer_drives_rules_and_evidence(tmp_path):
    from fastapi.testclient import TestClient

    from backend.main import app

    c = TestClient(app)
    img = _demo_jpg(tmp_path, "IMG_1530.jpg")
    with open(img, "rb") as f:
        r = c.post("/api/projects/BV-RIEM/captures", data={"kind": "photo", "captured_at": "2026-11-20T15:30:00+01:00"},
                   files={"file": ("IMG_1530.jpg", f, "image/jpeg")})
    assert r.status_code == 200
    cap = [x for x in c.get("/api/projects/BV-RIEM/captures", params={"date": "2026-11-20"}).json()
           if x["kind"] == "photo"][-1]
    assert cap["status"] == "awaiting_answer" and not cap["event_ids"]
    assert cap["followup"]["subtype"] == "crack" and "Vorleistung" in cap["followup"]["question"]
    full = c.get(f"/api/captures/{cap['capture_id']}").json()
    by_src = {}
    for e in full["evidence"]:
        by_src.setdefault(e["source"], []).append(e)
    assert len(by_src["ai_vision"]) == 2 and all(e["meta"]["status"] == "ai" for e in by_src["ai_vision"])
    assert len(by_src["photo"]) == 3  # Original + 2 bbox-Ausschnitte (Beleg ist das Bild)
    assert all(e["quote"] == "" for e in by_src["photo"])  # keine KI-Beschreibung im Fotobeleg

    r = c.post(f"/api/captures/{cap['capture_id']}/answer",
               data={"mode": "note", "text": "Das ist eine Vorleistung vom Rohbauer, nicht unsere Leistung. "
                                             "Der Riss ist seit heute Morgen zu sehen."})
    assert r.status_code == 200
    cap = c.get(f"/api/captures/{cap['capture_id']}").json()
    assert cap["status"] == "done" and len(cap["event_ids"]) == 1
    ev = c.get(f"/api/events/{cap['event_ids'][0]}").json()
    assert ev["type"] == "quality_defect" and ev["attrs"]["own_work"] is False
    assert ev["sphere"] == "AG" and ev["recommended_document"]["kind"] == "bedenkenanzeige"
    ai = {e["meta"]["subtype"]: e for e in ev["evidence_docs"] if e["source"] == "ai_vision"}
    assert ai["crack"]["meta"]["status"] == "corroborated"  # Antwort nennt den Riss
    assert ai["damage"]["meta"]["status"] == "ai"  # Abplatzung nicht erwähnt → bleibt Hinweis
    r = c.post(f"/api/evidence/{ai['damage']['evidence_id']}/review", json={"action": "confirm"})
    assert r.json()["meta"]["status"] == "confirmed"

    # Entwurf: KI-Beobachtungen hinten nummeriert, unbestätigte nicht als Sachverhalt zitiert
    letter = c.post(f"/api/events/{ev['event_id']}/draft").json()
    srcs = [e["source"] for e in letter["evidence"]]
    assert "ai_vision" in srcs and srcs.index("engine") < srcs.index("ai_vision")

    # Löschen entfernt Ausschnitte und das Ereignis samt Entwurf
    crops = [e["file"] for e in by_src["photo"] if e["meta"].get("role") == "crop"]
    r = c.delete(f"/api/captures/{cap['capture_id']}")
    assert r.status_code == 200 and set(crops) <= set(r.json().get("derived_files_deleted", []))


def test_photo_obstruction_owner_contractor_suggests_behinderungsanzeige(tmp_path):
    from fastapi.testclient import TestClient

    from backend.main import app

    c = TestClient(app)
    img = _demo_jpg(tmp_path, "IMG_1545.jpg")
    with open(img, "rb") as f:
        c.post("/api/projects/BV-RIEM/captures", data={"kind": "photo", "captured_at": "2026-11-20T15:45:00+01:00"},
               files={"file": ("IMG_1545.jpg", f, "image/jpeg")})
    cap = [x for x in c.get("/api/projects/BV-RIEM/captures", params={"date": "2026-11-20"}).json()
           if x["kind"] == "photo"][-1]
    assert cap["followup"]["question"].startswith("Wessen Material")
    c.post(f"/api/captures/{cap['capture_id']}/answer",
           data={"mode": "note", "text": "Die Steine gehören der Maurerfirma, die im Auftrag des Bauherrn arbeitet. "
                                         "Seit 14 Uhr kommt kein Lkw mehr zur Bodenplatte."})
    cap = c.get(f"/api/captures/{cap['capture_id']}").json()
    ev = c.get(f"/api/events/{cap['event_ids'][0]}").json()
    assert ev["type"] == "third_party_interference" and ev["attrs"]["predecessor_by_owner"] is True
    assert ev["sphere"] == "AG" and ev["recommended_document"]["kind"] == "behinderungsanzeige"
    # Korrigierte Antwort neu auswerten: Foto + KI-Beobachtungen bleiben, Ereignis entsteht neu
    r = c.patch(f"/api/captures/{cap['capture_id']}",
                json={"text": "Das ist unser eigenes Material, Lieferung kam zu früh.", "reanalyze": True}).json()
    assert r["photo"]["evidence_id"] in r["evidence_ids"] and len(r["photo"]["observations"]) == 2
    assert c.get(f"/api/events/{ev['event_id']}").status_code == 404  # hing nur noch am Foto
    new = c.get(f"/api/events/{r['event_ids'][0]}").json()
    assert new["sphere"] == "AN" and new["recommended_document"]["kind"] == "bautagebuch"
    assert any("im Auftrag des AG" in w for w in new["warnings"])  # Verursacher unklar → Rückfrage im Dashboard


def test_demo_photos_skipped_are_attachments_and_marked_in_report():
    from sitevox import store
    from sitevox.export import daily_report

    caps = [x for x in store.captures("BV-RIEM", "2026-11-20") if x["kind"] == "photo" and x["title"].startswith("Foto 07:31")]
    assert caps and caps[0]["status"] == "done" and caps[0]["answer"]["mode"] == "skip"
    plan = next(e for e in store.events("BV-RIEM", "2026-11-20") if e["type"] == "planlieferverzug")
    assert caps[0]["photo"]["evidence_id"] in plan["evidence"]
    rep = daily_report.build("BV-RIEM", "2026-11-20")
    ph = next(p for p in rep["photos"] if "07:31" in p["timestamp"])
    assert "KI-Beobachtung" in ph["caption_de"] and "nicht geprüft" in ph["caption_de"]


def test_vision_uses_structured_llm_with_retry(tmp_path, monkeypatch):
    """GPU-Pfad ohne GPU: Bild geht als data-URI an llm.structured; Schemaverletzung → Retry mit Fehler-Feedback."""
    import json as _json

    from sitevox import llm, settings
    from sitevox.understand import vision

    calls = []

    def fake_complete(self, schema, msgs, *, n, temperature):
        calls.append(msgs)
        if len(calls) == 1:
            return ['{"observations": [{"category": "defect"}]}']  # subtype/description fehlen
        return [_json.dumps({"summary": "Riss sichtbar.", "observations": [
            {"category": "defect", "subtype": "crack", "description": "Riss", "bbox": [100, 100, 400, 500],
             "severity": "high", "visual_conf": 0.9}]})]

    monkeypatch.setattr(settings, "is_demo", lambda: False)
    monkeypatch.setattr(llm.LLM, "_complete", fake_complete)
    img = _demo_jpg(tmp_path, "real.jpg")
    out = vision.analyze(img, "BV-RIEM", activities_today=["Wände EG"])
    assert out["analysis"]["observations"][0]["subtype"] == "crack" and len(calls) == 2
    first = calls[0][0]["content"]
    assert first[0]["type"] == "image_url" and first[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "Wände EG" in first[1]["text"] and "ungültig" in calls[1][-1]["content"]


def test_asr_faster_whisper_uses_language_prompt(monkeypatch, tmp_path):
    """Regression: faster-whisper-Pfad lief nach dem Merge auf einen NameError (vocab)."""
    import types

    from sitevox.understand import asr

    calls: list[dict] = []

    class Model:
        def detect_language(self, **kw):
            return None, None, [("tr", 0.9), ("de", 0.1)]

        def transcribe(self, audio, **kw):
            calls.append(kw)
            w = types.SimpleNamespace(word="Achse", start=0.0, end=0.4, probability=0.9)
            seg = types.SimpleNamespace(start=0.0, end=0.4, text="Achse C", words=[w])
            return iter([seg]), types.SimpleNamespace(duration=0.4)

    monkeypatch.setitem(sys.modules, "faster_whisper",
                        types.SimpleNamespace(decode_audio=lambda p: [0.0] * 16000, WhisperModel=None))
    monkeypatch.setattr(asr, "_fw_model", lambda: Model())
    monkeypatch.setattr(asr.settings, "is_demo", lambda: False)
    cfg = {**asr.settings.models()["asr"], "backend": "faster_whisper", "language": "auto"}
    monkeypatch.setattr(asr, "_asr_cfg", lambda: cfg)
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"")
    res = asr.transcribe(wav, "BV-RIEM")
    assert calls[0]["language"] == "tr" and calls[0]["initial_prompt"] == asr._prompt_for("tr")
    assert calls[0]["hotwords"] == " ".join(cfg.get("hotwords", [])) or None
    assert res["text"] == "Achse C" and res["language"] == "tr" and "vocabulary" not in res


def test_light_document_parser_docx(tmp_path):
    import docx

    from sitevox.understand import documents

    d = docx.Document()
    d.add_paragraph("Bewehrungsplan Achse D/7, Lieferung durch Stahlbau Huber GmbH")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Pos.", "Kurztext"
    t.cell(1, 0).text, t.cell(1, 1).text = "05.010", "Filigrandecke C25/30"
    f = tmp_path / "Planliste.docx"
    d.save(f)
    r = documents._light(f)
    assert r["backend"] == "light" and "Achse D/7" in r["pages"][0]["text"]
    assert r["tables"][0]["rows"][0][1] == "Filigrandecke C25/30"


def test_ocr_image_text(tmp_path, monkeypatch):
    pytest.importorskip("rapidocr")
    from PIL import Image, ImageDraw, ImageFont

    from sitevox.understand import ocr

    monkeypatch.setenv("SITEVOX_OCR", "1")
    img = Image.new("RGB", (900, 160), "white")
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(str(ROOT / "sitevox" / "export" / "fonts" / "DDINPro-Regular.ttf"), 40)
    d.text((20, 20), "Lieferschein Betonwerk Müller GmbH", fill="black", font=f)
    d.text((20, 90), "Achse C/4 Bodenplatte C30/37", fill="black", font=f)
    p = tmp_path / "schild.png"
    img.save(p)
    text = ocr.image_text(p)
    if not text:
        pytest.skip("OCR-Modell nicht verfügbar (offline?)")
    lines = text.splitlines()
    assert lines[0] == "Lieferschein Betonwerk Müller GmbH"
    assert "Achse C/4" in lines[1] and "C30/37" in lines[1]


def test_gaeb_export_and_reimport_roundtrip(tmp_path):
    from fastapi.testclient import TestClient

    from backend.main import app
    from sitevox import editing, pipeline, rag, store

    c = TestClient(app)
    lv = next(d for d in c.get("/api/projects/BV-RIEM/knowledge").json() if d["title"].startswith("Leistungsverzeichnis"))
    assert c.get(f"/api/documents/{lv['doc_id']}").json()["gaeb_exportable"]
    r = c.get(f"/api/documents/{lv['doc_id']}/gaeb", params={"phase": "83"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    xml = r.content.decode("utf-8")
    assert "GAEB_DA_XML/DA83/3.3" in xml and "Betonstahl B500B" in xml and "<DP>83</DP>" in xml
    assert c.get(f"/api/documents/{lv['doc_id']}/gaeb", params={"phase": "99"}).status_code == 400
    legal = next(d for d in c.get("/api/projects/BV-RIEM/knowledge").json() if d["collection"] == "legal")
    assert c.get(f"/api/documents/{legal['doc_id']}/gaeb").status_code == 400  # keine LV-Positionen
    # Re-Import der exportierten Datei als neues LV-Dokument
    f = tmp_path / "Rohbau.x83"
    f.write_bytes(r.content)
    cap = pipeline.ingest("BV-RIEM", "document", file=f, captured_at="2026-11-20T16:00:00+01:00",
                          meta={"doc_type": "dokument", "doc_title": "Rohbau GAEB"})
    try:
        d = store.get("documents", cap["capture_id"])
        assert d["kind"] == "lv" and d["gaeb"]["phase"] == "83" and d["gaeb"]["format"].startswith("DA XML")
        items = {i["kurztext"]: i for i in d["lv_items"]}
        orig = store.get("documents", lv["doc_id"])
        n_orig = sum(len(t["rows"]) for t in orig["tables"])
        assert d["gaeb"]["positions"] == n_orig == len(d["lv_items"])
        b = items["Betonstahl B500B liefern, schneiden, biegen, verlegen"]
        assert b["oz"] == "03.0030" and b["menge"] == "64" and b["einheit"] == "t"
        assert d["tables"][0]["header"][:4] == ["Pos.", "Kurztext", "Menge", "Einheit"]
        # LV-Prüfung erkennt das GAEB-LV am Dokumenttyp, auch ohne "LV" im Titel
        hits = [h for h in rag.index().search("Betonstahl B500B", project_id="BV-RIEM", collection="project", k=8)
                if h["doc_id"] == d["doc_id"]]
        assert hits and hits[0]["kind"] == "lv"
    finally:
        editing.delete_document(cap["capture_id"], "test")


def test_gaeb_items_from_tables_and_oz_normalisation():
    from sitevox.understand import gaeb_io

    items = gaeb_io.items_from_tables([
        {"header": ["Pos.", "Kurztext", "Menge", "Einheit"], "rows": [["01.010", "Baustelleneinrichtung", "1", "psch"],
                                                                     ["02.010", "Bodenaushub", "4.480,5", "m³"]]},
        {"header": ["Plan", "Index"], "rows": [["P-01", "b"]]},  # keine LV-Tabelle → ignoriert
    ])
    assert [i["oz"] for i in items] == ["01.010", "02.010"]
    lv = gaeb_io.to_lv(items, phase="83", titel_lv="LV")
    pos = lv.alle_positionen
    assert [p.oz for p in pos] == ["010010", "020010"] and pos[0].pauschale and str(pos[1].menge) == "4480.5"


def test_evidence_grouped_by_source():
    from fastapi.testclient import TestClient

    from backend.main import app

    c = TestClient(app)
    L = c.get("/api/letters/" + c.get("/api/projects/BV-RIEM/letters").json()[0]["letter_id"]).json()
    ids = [e["evidence_id"] for e in L["evidence"]]
    groups = c.get("/api/evidence-sources", params={"ids": ",".join(ids)}).json()
    assert len(groups) < len(ids)  # Mehrfach-Zitate aus derselben Quelle werden zusammengefasst
    assert sorted(i["evidence_id"] for g in groups for i in g["items"]) == sorted(ids)  # nichts geht verloren
    assert len({g["key"] for g in groups}) == len(groups)  # jede Quelle genau einmal
    multi_audio = next(g for g in groups if g["source"] == "audio" and len(g["items"]) > 1)
    assert multi_audio["file"] and multi_audio["transcript"]["segments"]  # ein Player, alle Abschnitte markierbar
    assert all(i["t_start"] is not None for i in multi_audio["items"])
    # gleiche Gruppierung im Schreiben (Liste "Alle Belege")
    assert len({e["source_key"] for e in L["evidence"]}) == len(groups)


def test_mail_account_bind_and_sync(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app
    from sitevox import mail_accounts
    from sitevox.understand import imap_mail

    def fake_test(acc, pw):
        if pw != "app-pw":
            raise imap_mail.MailError("Anmeldung abgelehnt")
        return {"ok": True, "messages": 3}

    raw = lambda mid, subj: (f"From: Ingenieurbüro Brandl <buero@ib-brandl.example>\r\nTo: bauleitung@hofbau.example\r\n"
                             f"Subject: {subj}\r\nDate: Fri, 20 Nov 2026 15:00:00 +0100\r\nMessage-ID: <{mid}>\r\n"
                             f"Content-Type: text/plain; charset=utf-8\r\n\r\nBV Riem RI-2026-014: Pläne Achse C folgen.\r\n"
                             ).encode("utf-8")
    other = (b"From: x@shop.example\r\nSubject: Angebot\r\nDate: Fri, 20 Nov 2026 15:00:00 +0100\r\n"
             b"Message-ID: <spam-1>\r\n\r\nRabatt\r\n")
    monkeypatch.setattr(imap_mail, "test", fake_test)
    monkeypatch.setattr(imap_mail, "fetch", lambda acc, pw, days: [raw("imap-1@x", "BV Riem Pläne"), other])
    c = TestClient(app)  # kein Netzwerkzugriff: test/fetch sind ersetzt
    bad = c.post("/api/projects/BV-RIEM/mail-accounts", json={"provider": "gmail", "address": "bl@hofbau.example",
                                                               "password": "falsch"})
    assert bad.status_code == 400 and "abgelehnt" in bad.json()["detail"]
    ms = c.post("/api/projects/BV-RIEM/mail-accounts", json={"provider": "microsoft", "address": "a@b.de",
                                                              "password": "x"})
    assert ms.status_code == 400  # Microsoft nur per Graph/OAuth
    acc = c.post("/api/projects/BV-RIEM/mail-accounts", json={"provider": "gmail", "address": "bl@hofbau.example",
                                                               "password": "app-pw"}).json()
    assert acc["imap_host"] == "imap.gmail.com" and acc["connected"] and "password" not in acc
    listed = c.get("/api/projects/BV-RIEM/mail-accounts").json()
    assert listed[0]["address"] == "bl@hofbau.example" and "password" not in listed[0]
    r = c.post(f"/api/projects/BV-RIEM/mail-accounts/{acc['account_id']}/sync").json()
    assert r == {"fetched": 2, "new": 1, "duplicate": 0, "other_project": 1}
    assert any(m["message_id"] == "imap-1@x" for m in c.get("/api/projects/BV-RIEM/mailbox").json())
    r = c.post(f"/api/projects/BV-RIEM/mail-accounts/{acc['account_id']}/sync").json()
    assert r["new"] == 0 and r["duplicate"] == 1  # keine Doppelungen
    # Passwort nur im Arbeitsspeicher: nach "Neustart" muss es neu eingegeben werden
    imap_mail.forget(acc["account_id"])
    assert c.post(f"/api/projects/BV-RIEM/mail-accounts/{acc['account_id']}/sync").status_code == 409
    assert c.delete(f"/api/projects/BV-RIEM/mail-accounts/{acc['account_id']}").json()["ok"]
    assert c.get("/api/projects/BV-RIEM/mail-accounts").json() == []


def test_photo_with_description_in_one_upload_skips_followup(tmp_path):
    """Neuer Ablauf: Foto + Beschreibung (Notiz) zusammen → keine Rückfrage, direkt Ereignis, Foto als Beleg."""
    from fastapi.testclient import TestClient

    from backend.main import app

    c = TestClient(app)
    img = _demo_jpg(tmp_path, "IMG_1530.jpg")
    with open(img, "rb") as f:
        r = c.post("/api/projects/BV-RIEM/captures",
                   data={"kind": "photo", "captured_at": "2026-11-20T15:40:00+01:00", "description_mode": "note",
                         "description_text": "Riss in der Wand, das ist eine Vorleistung vom Rohbauer, nicht unsere Leistung."},
                   files={"file": ("IMG_1530.jpg", f, "image/jpeg")})
    assert r.status_code == 200
    cap = [x for x in c.get("/api/projects/BV-RIEM/captures", params={"date": "2026-11-20"}).json()
           if x["kind"] == "photo" and x["captured_at"].startswith("2026-11-20T15:40")][-1]
    assert cap["status"] == "done" and not cap.get("followup")
    assert cap["answer"]["mode"] == "note" and "Vorleistung" in cap["text"]
    full = c.get(f"/api/captures/{cap['capture_id']}").json()
    srcs = {e["source"] for e in full["evidence"]}
    assert {"photo", "note"} <= srcs
    r = c.post("/api/projects/BV-RIEM/captures", data={"kind": "photo", "description_mode": "note"},
               files={"file": ("x.jpg", b"x", "image/jpeg")})
    assert r.status_code == 400
