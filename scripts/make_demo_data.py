#!/usr/bin/env python3
"""Erzeugt die Demo-Daten "Ein Tag im Leben eines Bauleiters" (BV Riem, Freitag 20.11.2026).

Ausgabe unter data/demo/BV-RIEM/:
  plan/Bauzeitenplan.xlsx         Bauzeitenplan (Import über sitevox.engine.schedule.import_plan)
  history/leistung.csv            Ist-Leistungen der Vortage
  inputs/2026-11-20/              Rohdaten des Tages: rec_*.wav, IMG_*.jpg, *.eml
  fixtures/asr|vision|llm|weather Replay-Ausgaben der Modelle für den Demo-Modus (kein GPU nötig)

  python scripts/make_demo_data.py            # Stille-WAVs als Audio-Platzhalter
  python scripts/make_demo_data.py --tts      # echte Sprachdateien mit macOS `say` (Stimme Anna)
  # Linux/Cluster: erst scripts/data/audio/tts_synthesize.py --demo (XTTS), dann dieses Skript ohne --tts –
  # vorhandene, nicht stille rec_*.wav werden behalten und die ASR-Fixture-Zeiten an ihre Dauer angepasst.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import wave
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "demo" / "BV-RIEM"
DAY = "2026-11-20"
TZ = "+01:00"
INP = DEMO / "inputs" / DAY
FX = DEMO / "fixtures"

# ----------------------------------------------------------------------------- Bauzeitenplan
PLAN = [
    # ID, Vorgang, Anfang, Ende, Menge, Einheit, LV-Pos, LV-Summe, Vorgänger, Aliase, Typ
    ("A10", "Baustelleneinrichtung", "2026-11-02", "2026-11-06", 1, "psch", "01.010", 40000, "", "Einrichtung", "Vorgang"),
    ("A20", "Aushub BA1", "2026-11-04", "2026-11-23", 4480, "m³", "02.010", 180000, "A10SS+2", "Aushub;Erdaushub;Baugrube", "Vorgang"),
    ("A30", "Schalung Rand", "2026-11-16", "2026-11-20", 300, "m", "03.020", 30000, "A20SS+8", "Randschalung;Schalung Rand BP", "Vorgang"),
    ("A40", "Bewehrung BP", "2026-11-11", "2026-11-20", 64, "t", "03.030", 120000, "A20SS+5", "Bewehrung Bodenplatte;Bewehrung", "Vorgang"),
    ("A50", "Betonage BP", "2026-11-20", "2026-11-24", 255, "m³", "03.040", 50000, "A40FS-1;A30SS+4", "Betonage Bodenplatte;Betonage;Betonpumpe", "Vorgang"),
    ("A60", "Wände EG", "2026-11-30", "2026-12-16", 820, "m²", "04.010", 260000, "A50FS+3", "Wände Erdgeschoss", "Vorgang"),
    ("M1", "Vertragsfrist Rohbau EG", "2026-12-16", "2026-12-16", 0, "", "", 0, "A60FS+0", "", "Meilenstein"),
]
HISTORY = {
    "A10": [("2026-11-02", .2), ("2026-11-03", .2), ("2026-11-04", .2), ("2026-11-05", .2), ("2026-11-06", .2)],
    "A20": [("2026-11-04", 300), ("2026-11-05", 320), ("2026-11-06", 310), ("2026-11-09", 315), ("2026-11-10", 290),
            ("2026-11-11", 320), ("2026-11-12", 300), ("2026-11-13", 305), ("2026-11-16", 280), ("2026-11-17", 310),
            ("2026-11-18", 305), ("2026-11-19", 310)],
    "A30": [("2026-11-16", 58), ("2026-11-17", 62), ("2026-11-18", 57), ("2026-11-19", 60)],
    "A40": [("2026-11-11", 8.0), ("2026-11-12", 8.5), ("2026-11-13", 7.5), ("2026-11-16", 8.0), ("2026-11-17", 8.0),
            ("2026-11-18", 7.5), ("2026-11-19", 6.0)],
}

# ----------------------------------------------------------------------------- Sprachmemos (ASR-Ausgabe)
MEMOS = {
    "rec_0700": ("07:00", "Guten Morgen, Freitag, 20. November. Personal heute 14 Mann statt 16. Bei der Kolonne "
                          "Müller fehlen zwei Mann krank, die sind heute nur zu sechst. Wetter Regen, so um die 4 Grad."),
    "rec_0730": ("07:30", "Achse C. Die Bewehrungspläne für Achse C, Index b, liegen immer noch nicht vor, obwohl das "
                          "Ingenieurbüro Brandl die Pläne in der Baubesprechung für den 18.11. zugesagt hatte. Die "
                          "Kolonne Müller kann bis Mittag noch in den Achsen A und B verlegen, ab 12 Uhr haben die in "
                          "Achse C keinen Arbeitsbereich mehr. Damit ist die Betonage der Bodenplatte heute Nachmittag "
                          "nicht zu halten. Ich mache Fotos von Achse C."),
    "rec_0745": ("07:45", "Sieben Uhr fünfundvierzig. Lieferung Betonstahl B500B von Stahlhandel Huber, acht Tonnen, "
                          "Lieferschein 48213, abgeladen am Lagerplatz Nord. Die Fertigteiltreppen für Haus A vom "
                          "Bauherrn sind für heute 15 Uhr angekündigt."),
    "rec_0915": ("09:15", "Neun Uhr fünfzehn. Prüfingenieur Dr. Hartl hat die Bewehrung der Bodenplatte in Achse A und B "
                          "abgenommen, ohne Beanstandung, das Protokoll kommt per Mail. Turmdrehkran heute früh "
                          "geprüft, in Ordnung."),
    "rec_1002": ("10:02", "Zehn Uhr zwei. Der Bagger steht seit 10 Uhr, Hydraulikschlauch am Ausleger geplatzt. "
                          "Werkstatt ist informiert, der Monteur kommt gegen eins. Aushub BA1 steht solange komplett."),
    "rec_1130": ("11:30", "Elf Uhr dreißig. Frau Lechner vom Architekturbüro war zur Bauüberwachung da, Rundgang "
                          "Bodenplatte und Baugrube, keine Hinweise. Außerdem Lieferung Abstandhalter und "
                          "Schalungsanker von Baustoff Meier, zwei Paletten, Lieferschein M-7781."),
    "rec_1300": ("13:00", "13 Uhr. Betonpumpe für heute abbestellt, die Bewehrung in Achse C ist nicht fertig. Neuer "
                          "Betoniertermin erst, wenn die Pläne da sind und Achse C verlegt ist."),
    "rec_1630": ("16:30", "Tagesleistung 20. November. Aushub BA1 etwa 190 Kubik, der Bagger lief ab halb zwei "
                          "wieder. Bewehrung Bodenplatte 6,5 Tonnen verlegt, alles in Achse A und B. Schalung Rand 63 "
                          "Meter, damit ist die Randschalung fertig. Betonage null. Kernbohrungen noch nicht begonnen."),
}
LOW_SCORE = {"index": 0.58, "b,": 0.46, "brandl": 0.71, "hydraulikschlauch": 0.74, "ausleger": 0.79,
             "6,5": 0.83, "kubik,": 0.81, "190": 0.86}


def _score(word: str, key: str) -> float:
    w = word.lower()
    if w in LOW_SCORE:
        return LOW_SCORE[w]
    h = int(hashlib.md5(f"{key}{word}".encode()).hexdigest()[:4], 16) / 0xFFFF
    return round(0.9 + 0.08 * h, 3)


def asr_fixture(key: str, text: str, duration: float | None) -> dict:
    words = text.split()
    naive = sum(0.14 + 0.06 * len(w) + 0.08 for w in words)
    scale = (duration - 0.6) / naive if duration else 1.0
    t, segs, cur = 0.3, [], []
    for w in words:
        dur = (0.14 + 0.06 * len(w)) * scale
        cur.append({"word": w, "start": round(t, 2), "end": round(t + dur, 2), "score": _score(w, key)})
        t += dur + 0.08 * scale
        if w.endswith((".", "?", "!")):
            segs.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(x["word"] for x in cur),
                         "words": cur})
            cur = []
    if cur:
        segs.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(x["word"] for x in cur),
                     "words": cur})
    return {"language": "de", "duration": round(t + 0.3, 2), "segments": segs}


def _has_speech(path: Path) -> bool:
    if not path.exists():
        return False
    import array

    with wave.open(str(path)) as w:
        if w.getsampwidth() != 2:
            return True
        a = array.array("h", w.readframes(w.getnframes()))
    return bool(a) and max(abs(min(a)), max(a)) > 30


def write_audio(key: str, text: str, tts: bool) -> float:
    out = INP / f"{key}.wav"
    if tts and shutil.which("say") and shutil.which("afconvert"):
        aiff = INP / f"{key}.aiff"
        subprocess.run(["say", "-v", "Anna", "-r", "165", "-o", str(aiff), text], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff), str(out)], check=True)
        aiff.unlink()
    elif _has_speech(out):  # z. B. von scripts/data/audio/tts_synthesize.py --demo (XTTS) – nicht überschreiben
        print(f"behalte vorhandene Sprachaufnahme {out.name}")
    else:
        secs = len(text.split()) / 2.6 + 0.6
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
            w.writeframes(b"\x00\x00" * int(16000 * secs))
    with wave.open(str(out)) as w:
        return w.getnframes() / w.getframerate()


# ----------------------------------------------------------------------------- E-Mails
MAILS = {
    "mail_1102": {
        "time": "11:02", "from": "Architekturbüro Lechner <info@lechner-architekten.example>",
        "to": "J. Hofmann <bauleitung@hofbau.example>", "cc": "",
        "subject": "BV Riem – zusätzliche Kernbohrungen Bodenplatte",
        "body": "Guten Tag Herr Hofmann,\n\nnach Abstimmung mit der TGA-Planung bitten wir Sie, in der Bodenplatte "
                "Achse A–B zusätzlich 4 Kernbohrungen DN150 für die Grundleitungen der Haustechnik vorzusehen. Die "
                "Lage entnehmen Sie bitte der beigefügten Skizze. Die Ausführung soll in der nächsten Woche "
                "erfolgen.\n\nMit freundlichen Grüßen\nArchitekturbüro Lechner\ni. A. S. Lechner",
    },
    "mail_1215": {
        "time": "12:15", "from": "Ingenieurbüro Brandl <buero@ib-brandl.example>",
        "to": "J. Hofmann <bauleitung@hofbau.example>", "cc": "t.wagner@wohnbau-riem.example",
        "subject": "AW: BV Riem – Bewehrungspläne Achse C Index b",
        "body": "Hallo Herr Hofmann,\n\ndie Bewehrungspläne Achse C (Index b) sind noch in der Prüfung. Die Pläne "
                "kommen voraussichtlich Montag.\n\nViele Grüße\nIngenieurbüro Brandl",
    },
}


def write_mail(key: str, m: dict) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = m["from"], m["to"], m["subject"]
    if m["cc"]:
        msg["Cc"] = m["cc"]
    msg["Date"] = f"Fri, 20 Nov 2026 {m['time']}:00 {TZ.replace(':', '')}"
    msg["Message-ID"] = f"<{key}@demo.sitevox>"
    msg.set_content(m["body"])
    (INP / f"{key}.eml").write_bytes(bytes(msg))


# ----------------------------------------------------------------------------- Fotos
# "analysis" = Replay der Qwen3-VL-Ausgabe (Schema PhotoAnalysis): nur was zu sehen ist, keine Ursache/Schuld.
# Die Demo-Fotos werden ohne Antwort eingespielt (answer = skip) und hängen als Anlage an den Ereignissen.
PHOTOS = {
    "IMG_0731": {"time": "07:31", "label": "Achse C – Bewehrung unvollständig", "link": "planlieferverzug",
                 "analysis": {
                     "summary": "Bodenplatte: untere Bewehrungslage nur auf einem Teil der Fläche verlegt, obere Lage "
                                "fehlt. Stabstahl-Bündel und Abstandhalter liegen ungenutzt auf der nassen "
                                "Sauberkeitsschicht. Zwei Arbeiter stehen am Rand, es finden keine Verlegearbeiten "
                                "statt. Nebel, Pfützen auf der Sauberkeitsschicht.",
                     "scene": {"bauteil": "Bodenplatte Achse C", "stage": "untere Bewehrungslage teilweise verlegt",
                               "activity_guess": "Bewehrung Bodenplatte"},
                     "observations": [
                         {"category": "progress", "subtype": "stage_change",
                          "description": "Untere Bewehrungslage nur teilweise verlegt, obere Lage fehlt.",
                          "bbox": [0, 265, 790, 525], "severity": "medium", "visual_conf": 0.84},
                         {"category": "obstruction", "subtype": "material_storage",
                          "description": "Stabstahl-Bündel und Abstandhalter liegen ungenutzt auf der Sauberkeitsschicht.",
                          "bbox": [340, 380, 850, 670], "severity": "low", "visual_conf": 0.78},
                         {"category": "obstruction", "subtype": "standing_water",
                          "description": "Pfützen auf der Sauberkeitsschicht.",
                          "bbox": [420, 300, 990, 720], "severity": "low", "visual_conf": 0.63}],
                     "followup_question": "Warum ruhen die Bewehrungsarbeiten?"}},
    "IMG_1410": {"time": "14:10", "label": "Bagger nach Reparatur", "link": "equipment_failure",
                 "analysis": {
                     "summary": "Kettenbagger in der Baugrube mit Spundwandverbau wieder in Betrieb; Hydraulikschläuche "
                                "am Ausleger sichtbar. Aushub wird auf einen Muldenkipper geladen. Boden nass, Pfützen.",
                     "scene": {"bauteil": "Baugrube BA1", "stage": "Aushub läuft", "activity_guess": "Aushub"},
                     "observations": [
                         {"category": "progress", "subtype": "stage_change",
                          "description": "Bagger in Betrieb, Muldenkipper wird beladen.",
                          "bbox": [260, 120, 1000, 930], "severity": "low", "visual_conf": 0.88}],
                     "followup_question": "Welche Menge wurde heute ausgehoben?"}},
}
# Weitere Replay-Analysen für eigene Uploads im Demo-Modus (Dateiname = Schlüssel, z. B. IMG_1530.jpg).
# Nicht im Tagesablauf – zeigen Rückfrage → Antwort → Regelwerk (Mangel/Vorleistung, Behinderung durch Dritte).
UPLOAD_PHOTOS = {
    "IMG_1530": {"time": "15:30", "analysis": {
        "summary": "Wandfuß Achse 3: durchgehender Riss in der Betonoberfläche, daneben Abplatzung an der Kante.",
        "scene": {"bauteil": "Wand Achse 3", "stage": "ausgeschalt", "activity_guess": None},
        "observations": [
            {"category": "defect", "subtype": "crack", "description": "Durchgehender Riss in der Betonoberfläche am Wandfuß.",
             "bbox": [180, 300, 620, 900], "severity": "high", "visual_conf": 0.78},
            {"category": "defect", "subtype": "damage", "description": "Abplatzung an der Wandkante.",
             "bbox": [640, 520, 820, 700], "severity": "medium", "visual_conf": 0.55}],
        "followup_question": "Seit wann ist der Riss sichtbar?"}},
    "IMG_1545": {"time": "15:45", "analysis": {
        "summary": "Paletten mit Mauersteinen stehen auf der Zufahrt zur Bodenplatte, Durchfahrt für Lkw versperrt.",
        "scene": {"bauteil": "Zufahrt Bodenplatte", "stage": None, "activity_guess": "Betonage Bodenplatte"},
        "observations": [
            {"category": "obstruction", "subtype": "material_storage",
             "description": "Paletten mit Mauersteinen stehen auf der Zufahrt.",
             "bbox": [90, 380, 760, 950], "severity": "high", "visual_conf": 0.88},
            {"category": "obstruction", "subtype": "blocked_access",
             "description": "Durchfahrt für Lkw versperrt.", "bbox": None, "severity": "high", "visual_conf": 0.7}],
        "followup_question": "Wem gehört das Material?"}},
}
GPS = {"lat": 48.13052, "lon": 11.69548}


def vision_fixture(p: dict) -> dict:
    """Replay-Format für llm.structured(): {"exif": …, "base": PhotoAnalysis}."""
    return {"exif": {"gps": GPS, "taken_at": f"{DAY}T{p['time']}:00{TZ}"}, "base": p["analysis"]}


def write_photo(key: str, p: dict) -> None:
    out = INP / f"{key}.jpg"
    if out.exists() and out.stat().st_size > 50_000:  # echtes Demo-Foto liegt bereits vor → nicht überschreiben
        return
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        out.write_bytes(b"")
        return
    img = Image.new("RGB", (960, 640), (148, 152, 150))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 420, 960, 640], fill=(110, 112, 108))
    if "Bewehrung" in p["label"]:
        for x in range(40, 940, 28):
            d.line([(x, 430), (x - 60, 640)], fill=(90, 60, 45), width=4)
        for y in range(440, 640, 30):
            d.line([(0, y), (480, y)], fill=(90, 60, 45), width=4)
    else:
        d.rectangle([300, 260, 640, 420], fill=(225, 170, 40))
        d.line([(600, 280), (820, 120), (900, 330)], fill=(60, 60, 60), width=18)
    d.rectangle([0, 0, 960, 56], fill=(30, 30, 30))
    d.text((16, 18), f"BV Riem · {DAY} {p['time']} · {p['label']} (Demo-Platzhalter)", fill=(255, 255, 255))
    exif = img.getexif()
    exif[0x0132] = f"{DAY.replace('-', ':')} {p['time']}:00"
    img.save(out, quality=85, exif=exif)


# ----------------------------------------------------------------------------- LLM-Fixtures
def ev(**kw):
    base = dict(end_time=None, affected_activities=[], resource_effects=[], responsible_party_guess="unklar",
                responsible_rationale="", impact_estimate_days=None, blocked_until=None, owner_supplied_material=None,
                predecessor_by_owner=None, own_work=None, work_started=None, ordered_by=None)
    base.update(kw)
    return base


EXTRACT = {
    "rec_0700": {"base": {
        "summary": "Personal 14 von 16; Kolonne Müller zwei Mann krank; Regen, ca. 4 °C.",
        "events": [ev(type="worker_shortage", description="Bei der Kolonne Müller fehlen zwei Mitarbeiter krankheitsbedingt.",
                      cause="Krankheit, 2 Mann", start_time="07:00", affected_activities=["Bewehrung BP"],
                      responsible_party_guess="AN", responsible_rationale="Eigene Personaldisposition des AN.",
                      own_work=True,
                      quotes=["Bei der Kolonne Müller fehlen zwei Mann krank, die sind heute nur zu sechst"])],
        "progress": [],
        "staffing": [{"crew": "Gesamt", "present": 14, "absent": 2, "reason": "krank",
                      "quote": "Personal heute 14 Mann statt 16"},
                     {"crew": "Kolonne Müller", "present": 6, "absent": 2, "reason": "krank",
                      "quote": "Bei der Kolonne Müller fehlen zwei Mann krank, die sind heute nur zu sechst"}],
        "open_items": []},
        "variants": [{}, {}, {}, {}, {}]},
    "rec_0730": {"base": {
        "summary": "Bewehrungspläne Achse C (Index b) fehlen trotz Zusage; Betonage BP heute nicht möglich.",
        "events": [ev(type="planlieferverzug",
                      description="Die Bewehrungspläne Achse C (Index b) liegen trotz Zusage für den 18.11. nicht vor.",
                      cause="Fehlende Bewehrungspläne Achse C, Index b (Ingenieurbüro Brandl)", start_time="07:30",
                      affected_activities=["Bewehrung BP Achse C", "Betonage BP"],
                      resource_effects=[{"resource": "Kolonne Müller", "status": "restricted", "start_time": "12:00",
                                         "end_time": None}],
                      responsible_party_guess="AG",
                      responsible_rationale="Die Planbeistellung durch die Tragwerksplanung des AG ist eine "
                                            "Mitwirkungspflicht des Auftraggebers.",
                      impact_estimate_days=2,
                      quotes=["Die Bewehrungspläne für Achse C, Index b, liegen immer noch nicht vor, obwohl das "
                              "Ingenieurbüro Brandl die Pläne in der Baubesprechung für den 18.11. zugesagt hatte",
                              "ab 12 Uhr haben die in Achse C keinen Arbeitsbereich mehr",
                              "Damit ist die Betonage der Bodenplatte heute Nachmittag nicht zu halten"])],
        "progress": [], "staffing": [], "open_items": []},
        "variants": [{}, {"events.0.impact_estimate_days": 1}, {},
                     {"events.0.responsible_party_guess": "neutral", "events.0.impact_estimate_days": 3}, {}]},
    "rec_0745": {"base": {
        "summary": "Lieferung Betonstahl 8 t (Stahlhandel Huber); Fertigteiltreppen Haus A (AG) für 15 Uhr angekündigt.",
        "events": [], "progress": [], "staffing": [], "open_items": [],
        "log_entries": [
            {"kind": "delivery", "text": "Betonstahl B500B, 8 t, von Stahlhandel Huber geliefert und am Lagerplatz Nord abgeladen.",
             "time": "07:40", "quote": "Lieferung Betonstahl B500B von Stahlhandel Huber, acht Tonnen, Lieferschein 48213",
             "material": "Betonstahl B500B", "quantity": 8, "unit": "t", "supplier": "Stahlhandel Huber",
             "supplied_by": "AN", "delivery_note_no": "48213", "arrived": True, "activity": "Bewehrung BP"},
            {"kind": "delivery", "text": "Fertigteiltreppen Haus A (Beistellung AG) für 15:00 Uhr angekündigt.",
             "time": "07:45", "quote": "Die Fertigteiltreppen für Haus A vom Bauherrn sind für heute 15 Uhr angekündigt",
             "material": "Fertigteiltreppen Haus A", "quantity": 4, "unit": "St", "supplier": "Wohnbau Riem (Beistellung)",
             "supplied_by": "AG", "arrived": False, "expected_date": "2026-11-20", "expected_time": "15:00"}]},
        "variants": [{}, {}, {}, {}, {}]},
    "rec_0915": {"base": {
        "summary": "Bewehrungsabnahme Achse A/B durch Prüfingenieur ohne Beanstandung; Kran geprüft.",
        "events": [], "progress": [], "staffing": [], "open_items": [],
        "log_entries": [
            {"kind": "inspection", "text": "Abnahme der Bewehrung Bodenplatte, Achsen A und B, durch den Prüfingenieur.",
             "time": "09:15", "quote": "Prüfingenieur Dr. Hartl hat die Bewehrung der Bodenplatte in Achse A und B abgenommen, ohne Beanstandung",
             "party": "Prüfingenieur Dr. Hartl", "result": "ohne Beanstandung, Protokoll folgt per E-Mail",
             "activity": "Bewehrung BP"},
            {"kind": "equipment_use", "text": "Turmdrehkran vor Arbeitsbeginn geprüft.", "time": "07:00",
             "quote": "Turmdrehkran heute früh geprüft, in Ordnung", "resource": "Turmdrehkran", "state": "checked_ok"}]},
        "variants": [{}, {}, {}, {}, {}]},
    "rec_1130": {"base": {
        "summary": "Bauüberwachung Architekturbüro Lechner ohne Hinweise; Lieferung Abstandhalter/Schalungsanker.",
        "events": [], "progress": [], "staffing": [], "open_items": [],
        "log_entries": [
            {"kind": "visit", "text": "Bauüberwachung durch das Architekturbüro Lechner: Rundgang Bodenplatte und Baugrube.",
             "time": "11:00", "quote": "Frau Lechner vom Architekturbüro war zur Bauüberwachung da, Rundgang Bodenplatte und Baugrube, keine Hinweise",
             "party": "Architekturbüro Lechner (Bauüberwachung)", "result": "keine Hinweise"},
            {"kind": "delivery", "text": "Abstandhalter und Schalungsanker, 2 Paletten, von Baustoff Meier geliefert.",
             "time": "11:25", "quote": "Lieferung Abstandhalter und Schalungsanker von Baustoff Meier, zwei Paletten, Lieferschein M-7781",
             "material": "Abstandhalter und Schalungsanker", "quantity": 2, "unit": "Pal.", "supplier": "Baustoff Meier",
             "supplied_by": "AN", "delivery_note_no": "M-7781", "arrived": True}]},
        "variants": [{}, {}, {}, {}, {}]},
    "rec_1002": {"base": {
        "summary": "Bagger seit 10:00 Uhr defekt (Hydraulikschlauch), Aushub BA1 steht.",
        "events": [ev(type="equipment_failure",
                      description="Der Bagger steht seit 10 Uhr wegen eines geplatzten Hydraulikschlauchs am Ausleger.",
                      cause="Hydraulikschlauch am Ausleger geplatzt", start_time="10:00",
                      affected_activities=["Aushub BA1"],
                      resource_effects=[{"resource": "Bagger", "status": "idle", "start_time": "10:00", "end_time": None}],
                      responsible_party_guess="AN", responsible_rationale="Eigenes Gerät des AN.",
                      quotes=["Der Bagger steht seit 10 Uhr, Hydraulikschlauch am Ausleger geplatzt",
                              "Aushub BA1 steht solange komplett"])],
        "progress": [], "staffing": [], "open_items": []},
        "variants": [{}, {}, {}, {}, {}]},
    "mail_1102": {"base": {
        "summary": "Architekturbüro Lechner fordert 4 zusätzliche Kernbohrungen DN150 in der Bodenplatte.",
        "events": [ev(type="additional_work",
                      description="Das Architekturbüro Lechner fordert zusätzlich 4 Kernbohrungen DN150 in der "
                                  "Bodenplatte für Grundleitungen der Haustechnik.",
                      cause="Zusätzliche Kernbohrungen DN150 (4 Stück) in der Bodenplatte", start_time="11:02",
                      responsible_party_guess="AG",
                      responsible_rationale="Vom Planer des AG geforderte, im Vertrag nicht vorgesehene Leistung.",
                      work_started=False, ordered_by="Architekturbüro Lechner",
                      quotes=["in der Bodenplatte Achse A–B zusätzlich 4 Kernbohrungen DN150 für die Grundleitungen "
                              "der Haustechnik vorzusehen", "Die Ausführung soll in der nächsten Woche erfolgen"])],
        "progress": [], "staffing": [], "open_items": []},
        "variants": [{}, {"events.0.type": "leistungsaenderung"}, {}, {"events.0.responsible_party_guess": "unklar"},
                     {"events.0.type": "leistungsaenderung"}]},
    "mail_1215": {"base": {
        "summary": "IB Brandl: Pläne Achse C noch in Prüfung, voraussichtlich Montag.",
        "events": [ev(type="planlieferverzug",
                      description="Das Ingenieurbüro Brandl teilt mit, dass die Bewehrungspläne Achse C (Index b) noch "
                                  "in Prüfung sind und voraussichtlich Montag kommen.",
                      cause="Pläne Achse C in Prüfung", affected_activities=["Bewehrung BP Achse C"],
                      responsible_party_guess="AG", responsible_rationale="Planlieferung durch Planer des AG.",
                      blocked_until="2026-11-23",
                      quotes=["die Bewehrungspläne Achse C (Index b) sind noch in der Prüfung",
                              "Die Pläne kommen voraussichtlich Montag"])],
        "progress": [], "staffing": [], "open_items": []},
        "variants": [{}, {}, {"events.0.blocked_until": "2026-11-24"}, {}, {}]},
    "rec_1300": {"base": {
        "summary": "Betonpumpe abbestellt, Bewehrung Achse C nicht fertig.",
        "events": [ev(type="planlieferverzug",
                      description="Die Betonpumpe wurde für heute abbestellt, da die Bewehrung in Achse C nicht fertig ist.",
                      cause="Bewehrung Achse C wegen fehlender Pläne nicht fertig", start_time="13:00",
                      affected_activities=["Betonage BP", "Bewehrung BP Achse C"],
                      resource_effects=[{"resource": "Betonpumpe", "status": "planned_not_started",
                                         "start_time": "13:00", "end_time": "17:00"}],
                      responsible_party_guess="AG", responsible_rationale="Folge der fehlenden Pläne.",
                      quotes=["Betonpumpe für heute abbestellt, die Bewehrung in Achse C ist nicht fertig"])],
        "progress": [], "staffing": [], "open_items": []},
        "variants": [{}, {}, {}, {}, {}]},
    "rec_1630": {"base": {
        "summary": "Tagesleistung: Aushub 190 m³, Bewehrung 6,5 t, Schalung Rand 63 m, Betonage 0.",
        "events": [ev(type="equipment_failure", description="Der Bagger lief ab 13:30 Uhr wieder.",
                      cause="Reparatur Hydraulikschlauch abgeschlossen", start_time="10:00", end_time="13:30",
                      affected_activities=["Aushub BA1"],
                      resource_effects=[{"resource": "Bagger", "status": "idle", "start_time": "10:00",
                                         "end_time": "13:30"}],
                      responsible_party_guess="AN", responsible_rationale="Eigenes Gerät.",
                      quotes=["der Bagger lief ab halb zwei wieder"]),
                   ev(type="additional_work", description="Die Kernbohrungen wurden noch nicht begonnen.",
                      cause="Zusätzliche Kernbohrungen DN150", work_started=False, responsible_party_guess="AG",
                      quotes=["Kernbohrungen noch nicht begonnen"])],
        "progress": [{"activity": "Aushub BA1", "quantity": 190, "unit": "m³", "quote": "Aushub BA1 etwa 190 Kubik"},
                     {"activity": "Bewehrung BP", "quantity": 6.5, "unit": "t",
                      "quote": "Bewehrung Bodenplatte 6,5 Tonnen verlegt"},
                     {"activity": "Schalung Rand", "quantity": 63, "unit": "m", "quote": "Schalung Rand 63 Meter"},
                     {"activity": "Betonage BP", "quantity": 0, "unit": "m³", "quote": "Betonage null"}],
        "staffing": [], "open_items": []},
        "variants": [{}, {}, {}, {}, {}]},
    "protokoll_bb07": {"base": {"summary": "Baubesprechung Nr. 7", "events": [], "progress": [], "staffing": [],
                                "open_items": []}, "variants": [{}]},
}
MINUTES = {"minutes_protokoll_bb07": {"samples": [{
    "summary": ["Vertragsfrist Rohbau EG 16.12.2026 bestätigt",
                "Ingenieurbüro Brandl sagt Bewehrungspläne Achse C (Index b) für den 18.11.2026 zu",
                "Betonage Bodenplatte für 20.11.2026 ab 13:00 Uhr vorgesehen, Pumpe durch AN bestellt",
                "Durchführungen TGA in der Bodenplatte noch in Abstimmung"],
    "open_items": [
        {"topic": "Bewehrungspläne Achse C (Index b) liefern", "responsible": "Ingenieurbüro Brandl (für AG)",
         "due": "2026-11-18", "quote": "Ingenieurbüro Brandl sagt die Bewehrungspläne Achse C (Index b) für den 18.11.2026 zu."},
        {"topic": "Absturzsicherung Baugrubenrand ergänzen", "responsible": "AN", "due": "2026-11-20",
         "quote": "Absturzsicherung Baugrubenrand wird durch AN bis 20.11.2026 ergänzt."},
        {"topic": "Abstimmung Durchführungen TGA in der Bodenplatte", "responsible": "Architekturbüro Lechner",
         "due": "2026-11-25", "quote": "Verantwortlich: Architekturbüro Lechner. Termin: 25.11.2026."}]}]}}


# Qwen3-8B-Entwürfe (Replay). Beleg-IDs entsprechen der Nummerierung im Composer.
# Satz 5 im Sachverhalt enthält bewusst ein Datum ohne Beleg (16.11.2026) → Faktenprüfung markiert es rot.
DRAFTS = {
    f"draft_planlieferverzug_{DAY}": {"samples": [{
        "sachverhalt": [
            {"text": "Gemäß Planlieferliste war der Bewehrungsplan der Bodenplatte Achse C (Index b) bis zum "
                     "18.11.2026 durch das Ingenieurbüro Brandl zu liefern; in der Baubesprechung Nr. 7 wurde dieser "
                     "Termin bestätigt.", "evidence": ["E-04", "E-05"]},
            {"text": "Am 20.11.2026 um 07:30 Uhr lagen die Bewehrungspläne Achse C (Index b) weiterhin nicht vor.",
             "evidence": ["E-01", "E-06"]},
            {"text": "Unsere Bewehrungskolonne konnte daher nur in den Achsen A und B verlegen; ab 12:00 Uhr stand in "
                     "Achse C kein Arbeitsbereich mehr zur Verfügung.", "evidence": ["E-02"]},
            {"text": "Das Ingenieurbüro Brandl teilte am 20.11.2026 um 12:15 Uhr mit, dass die Pläne noch in Prüfung "
                     "sind und voraussichtlich am Montag, 23.11.2026, geliefert werden.",
             "evidence": ["E-07", "E-08", "E-11"]},
            {"text": "Die fehlenden Pläne hatten wir bereits am 16.11.2026 telefonisch angemahnt.",
             "evidence": ["E-01"]},
        ],
        "auswirkungen": [
            {"text": "Die für den 20.11.2026 ab 13:00 Uhr vorgesehene Betonage der Bodenplatte konnte nicht beginnen; "
                     "die Betonpumpe wurde abbestellt.", "evidence": ["E-03", "E-09", "E-04"]},
            {"text": "Die Tagesleistung der Bewehrung betrug 6,5 t bei einem Tagessoll von 8 t.", "evidence": ["E-11"]},
            {"text": "Nach unserer Terminplanberechnung verschiebt sich das Ende der Bewehrung der Bodenplatte vom "
                     "20.11.2026 auf den 24.11.2026 und die Betonage auf den Zeitraum 24.11.2026 bis 26.11.2026.",
             "evidence": ["E-11"]},
            {"text": "Da diese Vorgänge auf dem kritischen Weg liegen, verschiebt sich die Fertigstellung der Wände EG "
                     "voraussichtlich vom 16.12.2026 auf den 18.12.2026; die Vertragsfrist Rohbau EG würde damit um 2 "
                     "Arbeitstage überschritten.", "evidence": ["E-11"]},
        ]}]},
    f"draft_additional_work_{DAY}": {"samples": [{
        "sachverhalt": [
            {"text": "Mit E-Mail vom 20.11.2026, 11:02 Uhr, forderte das Architekturbüro Lechner die Herstellung von "
                     "zusätzlich 4 Kernbohrungen DN150 in der Bodenplatte Achse A–B für die Grundleitungen der "
                     "Haustechnik.", "evidence": ["E-01"]},
            {"text": "Die Ausführung soll in der nächsten Woche erfolgen.", "evidence": ["E-02"]},
            {"text": "Eine entsprechende Position ist im Leistungsverzeichnis nicht enthalten.",
             "evidence": ["E-03", "E-06"]},
            {"text": "Mit der Ausführung wurde noch nicht begonnen.", "evidence": ["E-04"]},
        ],
        "auswirkungen": [
            {"text": "Für die Kernbohrungen entstehen zusätzliche Kosten für Gerät, Personal und Entsorgung, die von "
                     "den vereinbarten Preisen nicht erfasst sind.", "evidence": ["E-03"]},
            {"text": "Da die Anforderung durch das Architekturbüro Lechner erfolgte, bitten wir um Bestätigung durch "
                     "den Auftraggeber bzw. dessen bevollmächtigten Vertreter.", "evidence": ["E-01", "E-05"]},
        ]}]},
}


def weather_fixture() -> dict:
    hours = []
    precip = {7: .4, 8: .8, 9: 1.0, 10: .9, 11: .6, 12: .5, 13: .4, 14: .5, 15: .4, 16: .3, 17: .2}
    for h in range(24):
        hours.append({"timestamp": f"{DAY}T{h:02d}:00:00{TZ}", "temperature": round(2.6 + 1.6 * (1 - abs(h - 14) / 10), 1),
                      "precipitation": precip.get(h, 0.1), "wind_gust_speed": 22 + (h % 5) * 2,
                      "condition": "rain" if precip.get(h, 0) >= .3 else "cloudy"})
    return {"weather": hours, "sources": [{"station_name": "MUENCHEN-STADT", "observation_type": "forecast"}]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tts", action="store_true", help="Sprachdateien mit macOS say erzeugen")
    args = ap.parse_args()
    for d in (INP, FX / "asr", FX / "vision", FX / "llm", FX / "weather", DEMO / "plan", DEMO / "history"):
        d.mkdir(parents=True, exist_ok=True)

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Bauzeitenplan"
    ws.append(["ID", "Vorgang", "Anfang", "Ende", "Menge", "Einheit", "LV-Pos", "LV-Summe", "Vorgänger", "Aliase", "Typ"])
    for row in PLAN:
        ws.append(list(row))
    wb.save(DEMO / "plan" / "Bauzeitenplan.xlsx")
    with open(DEMO / "history" / "leistung.csv", "w", encoding="utf-8") as f:
        f.write("datum;vorgang;menge\n")
        for aid, rows in HISTORY.items():
            for d, q in rows:
                f.write(f"{d};{aid};{q}\n")

    manifest = []
    for key, (time, text) in MEMOS.items():
        dur = write_audio(key, text, args.tts)
        (FX / "asr" / f"{key}.json").write_text(json.dumps(asr_fixture(key, text, dur), ensure_ascii=False, indent=1))
        manifest.append({"kind": "audio", "file": f"{key}.wav", "time": time, "fixture": key})
    for key, m in MAILS.items():
        write_mail(key, m)
        manifest.append({"kind": "email", "file": f"{key}.eml", "time": m["time"], "fixture": key})
    for key, p in PHOTOS.items():
        write_photo(key, p)
        (FX / "vision" / f"{key}.json").write_text(json.dumps(vision_fixture(p), ensure_ascii=False, indent=1))
        manifest.append({"kind": "photo", "file": f"{key}.jpg", "time": p["time"], "title": f"Foto {p['time']} · {p['label']}",
                         "meta": {"link_event_type": p["link"]}, "answer": {"mode": "skip"}})
    for key, p in UPLOAD_PHOTOS.items():
        (FX / "vision" / f"{key}.json").write_text(json.dumps(vision_fixture(p), ensure_ascii=False, indent=1))
    for key, fx in {**{f"extract_{k}": v for k, v in EXTRACT.items()}, **MINUTES, **DRAFTS}.items():
        (FX / "llm" / f"{key}.json").write_text(json.dumps(fx, ensure_ascii=False, indent=1))
    (FX / "weather" / f"{DAY}.json").write_text(json.dumps(weather_fixture(), indent=1))
    manifest.sort(key=lambda m: m["time"])
    (DEMO / "inputs" / f"{DAY}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"Demo-Daten geschrieben nach {DEMO} ({len(manifest)} Erfassungen, TTS={'ja' if args.tts else 'nein'})")


if __name__ == "__main__":
    main()
