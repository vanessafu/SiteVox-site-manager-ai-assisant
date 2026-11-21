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
