#!/usr/bin/env python3
"""Auswertung eines Foto-zuerst-Bautags (gold-scenario 0.3/0.4: "captures" = Fotoserie + eine Notiz).

  python -m evaluation.eval_capture_scenario --run <SITEVOX_DATA>/run_output.json \
      --inputs data/raw/scenario_SCN-RIEM-0016_2026-11-23_de \
      --scenario data/demo/scenario/scenario_SCN-RIEM-0016_2026-11-23_de.json --out outputs/eval/<name>

Zuordnung System → Gold NUR über Belege: Ereignis/Tagebuch-Eintrag → Beleg → System-Erfassung → Eingabedatei
(run_output.inputs) → Gold-Erfassung (gold.json). Das System sieht gold.json nie.

Kennzahlen
  Ereignisse      Erkennung je Gold-Ereignis, Typ, Sphäre, Schreiben (Art), Fortschreibung von Vortagsereignissen
                  (kind follow_up / continues), Abschluss (closes → Ende gesetzt)
  Routine-Disziplin  Erfassungen OHNE Gold-Ereignis dürfen kein Ereignis erzeugen (Fehlalarm); Beinahe-Fälle
                  (near_miss, z. B. "Bagger läuft, Schlauch dicht") getrennt ausgewiesen
  Bautagebuch     neue log_entries: Lieferungen (Material, Menge, Lieferschein, angekommen/ausstehend) gegen
                  4_lieferungen; Geräte gegen 3_geraete; Routine-Erfassung mit passender Eintragsart
  Leistung/Personal  5_tagesleistung (Ist je Vorgang) · Personal gesamt (facts.personnel_total / 2_personal_summe)
  Nachrichten     gold action (E-Mail/interne Nachricht an Empfänger lt. Register): Entwurf vorhanden, Empfänger,
                  Pflichtinhalte (must_include, Schlüsselwort-Abdeckung ≈), verbotene Entwürfe (must_not)
  Fotos           Pflichtanlagen (action.attach) am Ereignis · unbrauchbare Bilder (usable=false) am Ereignis
  ASR             WER (kanonisch) je Sprachnotiz, Rauschart/SNR, Sprach-ID, asr_score
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation import metrics as M  # noqa: E402

TYPE_MAP = {"plan_delivery_delay": "planlieferverzug", "change_order": "leistungsaenderung",
            "weather": "weather_interruption"}
AG_PARTIES = {"AG-VERTRETER", "AG"}
LOG_FOR_PURPOSE = {"material": {"delivery"}, "equipment": {"equipment_use"},
                   "progress": {"work_done", "inspection", "visit", "progress", "staffing", "equipment_use"}}


def gold_doc_kind(doc: dict | None) -> str | None:
    if not doc:
        return None
    d = (doc.get("type") or "").lower()
    basis = " ".join(doc.get("basis") or [])
    if "behinderung" in d:
        return "behinderungsanzeige"
    if "bedenken" in d:
        return "bedenkenanzeige"
    if "mehrkosten" in d or "nachtrag" in d:
        return "nachtragsankuendigung" if "Abs. 5" in basis + d or "abs. 5" in d else "mehrkostenankuendigung"
    return d or None


def hhmm(x) -> str | None:
    m = re.search(r"(\d{1,2}):(\d{2})", str(x or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _num(x) -> float | None:
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(x if x is not None else ""))
    return float(m.group(0).replace(",", ".")) if m else None


def _tokens(s: str) -> set[str]:
    s = M.canonical(s)
    return {w for w in re.findall(r"[\wäöüß§./:-]+", s) if any(c.isdigit() for c in w) or len(w) > 3}


def key_coverage(items: list[str], text: str) -> tuple[int, int, list[str]]:
    """≈ Pflichtinhalt: ≥ 50 % der Schlüsselwörter (Zahlen, Wörter > 3 Zeichen) eines Punkts stehen im Entwurf.
    Grob (Synonyme/Übersetzung zählen nicht) – nur als Trend lesen."""
    t = M.canonical(text)
    hit, miss = 0, []
    for it in items:
        ks = _tokens(it)
        if ks and sum(k in t for k in ks) / len(ks) >= 0.5:
            hit += 1
        else:
            miss.append(it)
    return hit, len(items), miss


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--inputs", required=True, type=Path)
    ap.add_argument("--scenario", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    run = json.loads(a.run.read_text(encoding="utf-8"))
    gold = json.loads((a.inputs / "gold.json").read_text(encoding="utf-8"))
    sc = json.loads(a.scenario.read_text(encoding="utf-8"))
    er = sc.get("expected_report") or {}
    day = gold["date"]
    a.out.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ System-Erfassung → Gold-Erfassung
    note2cap = {f: cid for cid, g in gold["captures"].items() for f in (g.get("note_files") or [g["note_file"]])}
    sys2gold, sys2file = {}, {}
    for i in run["inputs"]:
        sys2gold[i["capture_id"]] = note2cap.get(i.get("capture_key") or i.get("note_file") or i["file"])
        sys2file[i["capture_id"]] = i["file"]
    ev_cap = run["evidence_capture"]
    caps = {c["capture_id"]: c for c in run["captures"]}
    logs = run.get("log_entries") or []

    def gold_caps_of(evidence: list[str]) -> set[str]:
        return {sys2gold.get(ev_cap.get(x)) for x in evidence} - {None}

    def photos_of(evidence: list[str]) -> set[str]:
        out = set()
        for x in evidence:
            f = sys2file.get(ev_cap.get(x)) or ""
            if f.startswith("photos/"):
                out.add(gold["photos"].get(Path(f).name))
        return out - {None}

    sys_rows = []
    for e in run["events"]:
        gc = gold_caps_of(e["evidence"])
        sys_rows.append({"event_id": e["event_id"], "date": e["date"], "type": e["type"], "sphere": e["sphere"],
                         "start": hhmm(e.get("start")), "end": hhmm(e.get("end")),
                         "doc": e["recommended_document"]["kind"] if e["recommended_document"].get("requires_letter") else None,
                         "letter_id": e.get("letter_id"), "gold_caps": sorted(gc), "photos": sorted(photos_of(e["evidence"])),
                         "carried": e["date"] < day, "description": (e.get("description") or "")[:160]})
    by_cap = defaultdict(list)
    for r in sys_rows:
        for g in r["gold_caps"]:
            by_cap[g].append(r)

    # ------------------------------------------------------------------ Gold-Ereignisse
    gold_rows, closes_rows = [], []
    letters = {l["letter_id"]: l for l in run["letters"] if l}
    for cid, g in gold["captures"].items():
        ge = (g["gold"] or {}).get("event")
        if g["gold"].get("closes"):
            target = g["gold"]["closes"]
            src = next((x for x, y in gold["captures"].items() if ((y["gold"] or {}).get("event") or {}).get("id") == target), None)
            hit = [r for r in by_cap.get(src, []) + by_cap.get(cid, []) if r["end"]]
            closes_rows.append({"capture": cid, "closes": target, "ok": bool(hit),
                                "sys": [f"{r['event_id']} {r['start']}–{r['end']}" for r in hit]})
        if not ge:
            continue
        ms = by_cap.get(cid, [])
        gt = TYPE_MAP.get(ge.get("type"), ge.get("type"))
        best = next((m for m in ms if m["type"] == gt), ms[0] if ms else None)
        gdoc = gold_doc_kind(ge.get("document"))
        follow = ge.get("kind") == "follow_up" or bool(ge.get("continues"))
        gold_rows.append({
            "gold": ge.get("id"), "capture": cid, "purpose": g["purpose"], "note": g["note_kind"], "type": gt,
            "sphere": ge.get("sphere"), "doc": gdoc, "follow_up": follow, "start": hhmm(ge.get("start")),
            "end": hhmm(ge.get("end")), "detected": bool(ms), "n_system": len(ms),
            "sys_event": best["event_id"] if best else None, "sys_type": best["type"] if best else None,
            "type_ok": bool(best and best["type"] == gt), "sys_sphere": best["sphere"] if best else None,
            "sphere_ok": bool(best and best["sphere"] == ge.get("sphere")),
            "sys_doc": best["doc"] if best else None, "doc_ok": bool(best and best["doc"] == gdoc),
            "continued_ok": (bool(best and best["carried"]) if follow else None),
            "sys_start": best["start"] if best else None, "sys_end": best["end"] if best else None})

    # ------------------------------------------------------------------ Routine-Disziplin (kein Ereignis aus Normalbetrieb)
    routine_rows = []
    for cid, g in gold["captures"].items():
        if (g["gold"] or {}).get("event"):
            continue
        ms = [r for r in by_cap.get(cid, []) if not r["carried"] or cid in r["gold_caps"]]
        new = [r for r in ms if not r["carried"]]
        sys_caps = [c for c, gg in sys2gold.items() if gg == cid]
        lk = sorted({l["kind"] for l in logs if l.get("capture_id") in sys_caps})
        if any(ev_cap.get(x) in sys_caps for p in run["progress"] for x in p.get("evidence_ids") or []):
            lk.append("progress")
        if any(ev_cap.get(s.get("evidence_id")) in sys_caps for s in run["staffing"]):
            lk.append("staffing")
        want = LOG_FOR_PURPOSE.get(g["purpose"], set())
        routine_rows.append({"capture": cid, "purpose": g["purpose"], "near_miss": (g["gold"] or {}).get("near_miss"),
                             "closes": (g["gold"] or {}).get("closes"), "false_events": [f"{r['event_id']} {r['type']}" for r in new],
                             "log_kinds": lk, "log_ok": bool(set(lk) & want) if want else None,
                             "text": " / ".join(gold["inputs"][f]["text"] for f in (g.get("note_files") or [g["note_file"]]))[:110]})
    false_alarm = [r for r in routine_rows if r["false_events"] and not r["closes"]]

    # ------------------------------------------------------------------ Bautagebuch: Lieferungen, Geräte
    dl = [l for l in logs if l["kind"] == "delivery"]
    deliv_rows = []
    for r in er.get("4_lieferungen") or []:
        keys = _tokens(r.get("item", ""))
        cand = sorted(dl, key=lambda l: -sum(k in M.canonical(" ".join(str(l.get(x) or "") for x in
                                                                        ("material", "text", "quote"))) for k in keys))
        best = cand[0] if cand and sum(k in M.canonical(" ".join(str(cand[0].get(x) or "") for x in
                                                                  ("material", "text", "quote"))) for k in keys) else None
        delivered = r.get("actual") is not None
        gq = _num(r.get("qty"))
        deliv_rows.append({
            "item": r["item"], "qty": r.get("qty"), "status": r.get("status"), "delivered": delivered,
            "logged": bool(best), "sys": (best or {}).get("material"), "sys_qty": (best or {}).get("quantity"),
            "qty_ok": bool(best and gq is not None and best.get("quantity") is not None and abs(best["quantity"] - gq) < 0.01),
            "arrived_ok": bool(best and (best.get("arrived") is not False) == delivered) if best else False,
            "note_ok": (bool(best and r["delivery_note"].replace(" ", "") in str(best.get("delivery_note_no") or "").replace(" ", ""))
                        if r.get("delivery_note") else None),
            # nicht gelieferte Posten erkennt das System u. U. als Ereignis (material_delay) statt Tagebuch
            "as_event": any(s["type"] == "material_delay" for s in sys_rows if not delivered)})
    eq = [l for l in logs if l["kind"] == "equipment_use"]
    equip_rows = []
    for r in er.get("3_geraete") or []:
        dev = r["device"].lower()
        stem = "kran" if "kran" in dev else dev[:5]
        hit = [l for l in eq if stem in str(l.get("resource") or "").lower() or stem in l.get("text", "").lower()]
        ev = [s for s in sys_rows if s["type"] in ("equipment_failure", "third_party_interference")
              and stem in s["description"].lower()]
        equip_rows.append({"device": r["device"], "ausfall": r.get("ausfall"), "logged": bool(hit) or bool(ev),
                           "states": sorted({l.get("state") or "–" for l in hit}),
                           "outage_ok": (bool(ev) or any(l.get("state") in ("idle", "restricted") for l in hit))
                           if r.get("ausfall") else None})

    # ------------------------------------------------------------------ Leistung / Personal
    prog = {p["activity_id"]: p["qty"] for p in run["progress"]}
    prog_rows = [{"activity": r["vorgang"], "gold": r["ist"], "system": prog.get(r["vorgang"]), "unit": r["einheit"],
                  "ok": (prog.get(r["vorgang"]) or 0) == r["ist"] if r["ist"] == 0 else
                  (prog.get(r["vorgang"]) is not None and abs(prog[r["vorgang"]] - r["ist"]) <= 0.01 * max(1, r["ist"]))}
                 for r in er.get("5_tagesleistung") or []]
    gold_total = (er.get("2_personal_summe") or {}).get("ist") or sum(r["ist"] for r in er.get("2_personal") or [])
    sys_total = sum(s["present"] for s in run["staffing"]) if run["staffing"] else None
    staff = {"gold_total": gold_total, "system_total": sys_total, "ok": sys_total == gold_total,
             "crews": [f"{s['crew']}={s['present']}" for s in run["staffing"]]}

    # ------------------------------------------------------------------ Nachrichten / Schreiben
    msg_rows = []
    for cid, g in gold["captures"].items():
        act = (g["gold"] or {}).get("action")
        if not act:
            continue
        ms = by_cap.get(cid, [])
        lids = [m["letter_id"] for m in ms if m["letter_id"]]
        to_ag = act.get("to") in AG_PARTIES
        txt = " ".join(json.dumps(letters[l], ensure_ascii=False) for l in lids if l in letters)
        h, n, miss = key_coverage(act.get("must_include") or [], txt) if txt else (0, len(act.get("must_include") or []),
                                                                                    act.get("must_include") or [])
        msg_rows.append({"capture": cid, "type": act["type"], "to": act["to"], "to_ag": to_ag,
                         "drafted": bool(lids), "letters": lids,
                         # Entwürfe des Systems gehen immer an den AG → nur bei AG-Empfänger richtig
                         "recipient_ok": bool(lids) and to_ag, "wrong_to_ag": bool(lids) and not to_ag,
                         "must_include_hit": h, "must_include_n": n, "missing": miss,
                         "attach_want": act.get("attach") or [],
                         "attach_got": sorted(set(act.get("attach") or []) & set().union(*[set(m["photos"]) for m in ms]) if ms else set())})
    must_docs = [d for d in er.get("documents_to_draft") or []]

    # ------------------------------------------------------------------ Fotos
    unusable = {p["id"] for g in gold["captures"].values() for p in g["photos"] if not p["usable"] and p["file"]}
    attached = set().union(*[set(r["photos"]) for r in sys_rows]) if sys_rows else set()
    att_want = sum(len(r["attach_want"]) for r in msg_rows)
    att_got = sum(len(r["attach_got"]) for r in msg_rows)
    avail = {p["id"] for g in gold["captures"].values() for p in g["photos"] if p["file"]}
    att_avail = sum(len(set(r["attach_want"]) & avail) for r in msg_rows)

    # ------------------------------------------------------------------ ASR
    asr_rows = []
    for i in run["inputs"]:
        f = i.get("note_file") or i["file"]
        if not f.startswith("audio/") or i["kind"] not in ("photo+note", "audio") or f not in gold["inputs"]:
            continue
        g, c = gold["inputs"][f], caps.get(i["capture_id"]) or {}
        tr = ((c.get("answer") or {}).get("transcript")) or {"text": c.get("transcript_text"), "language": c.get("language")}
        hyp = tr.get("text") or ""
        w = M.wer_counts(M.canonical(g["text"]), M.canonical(hyp))
        nh, nt = M.number_hits(g["text"], hyp)
        asr_rows.append({"file": f, "noise": g.get("noise_used", g["noise"]), "snr_db": g.get("snr_used", g["snr_db"]),
                         "accent": g.get("accent"), "wer": w["errors"] / max(1, w["n_ref"]), "errors": w["errors"],
                         "n_ref": w["n_ref"], "num_hit": nh, "num_total": nt, "lang": tr.get("language"),
                         "asr_score": (c.get("answer") or {}).get("asr_score", c.get("asr_score")),
                         "qc_pass": g.get("qc_pass"), "ref": g["text"], "hyp": hyp})

    # ------------------------------------------------------------------ Laufzeit (eine Kennzahl)
    # Verarbeitungszeit je Erfassung: Upload Fotoserie + Notiz → Ereignisse/Tagebuch gespeichert (ASR, VLM, Extraktion,
    # Regeln; ohne Schreiben-Entwurf). run_scenario misst die ganze Serie und schreibt sie an jedes Foto der Serie.
    per_cap = {}
    for i in run["inputs"]:
        per_cap.setdefault(i.get("capture_key") or i.get("note_file") or i["file"], (i.get("seconds"), i["file"]))
    secs = sorted(v[0] for v in per_cap.values() if v[0] is not None)
    q = lambda p_: secs[min(len(secs) - 1, int(round(p_ * (len(secs) - 1))))] if secs else None  # noqa: E731
    voice_caps = {k for k in per_cap if any(f.startswith("audio/") for g in gold["captures"].values()
                                                if k in (g.get("note_files") or [g["note_file"]])
                                                for f in (g.get("note_files") or [g["note_file"]]))}
    voice_s = sorted(per_cap[k][0] for k in voice_caps if per_cap[k][0] is not None)
    runtime = {"n": len(secs), "p50_s": q(0.5), "p95_s": q(0.95), "max_s": secs[-1] if secs else None,
               "p50_voice_s": voice_s[len(voice_s) // 2] if voice_s else None}

    # ------------------------------------------------------------------ Zusammenfassung
    n = len(gold_rows)
    det = [r for r in gold_rows if r["detected"]]
    fu = [r for r in gold_rows if r["follow_up"]]
    rat = lambda k, rows: (sum(bool(r[k]) for r in rows) / len(rows)) if rows else None  # noqa: E731
    S = {
        "events": {"gold": n, "detected": len(det), "recall": len(det) / n if n else None,
                   "type_acc": rat("type_ok", det), "sphere_acc": rat("sphere_ok", det), "doc_acc": rat("doc_ok", det),
                   "follow_up": len(fu), "continued_ok": sum(bool(r["continued_ok"]) for r in fu),
                   "fragmented": sum(r["n_system"] > 1 for r in gold_rows), "system_events": len(sys_rows),
                   "closes_ok": sum(r["ok"] for r in closes_rows), "closes": len(closes_rows)},
        "routine": {"captures": len(routine_rows), "false_alarm_captures": len(false_alarm),
                    "near_miss": sum(bool(r["near_miss"]) for r in routine_rows),
                    "near_miss_false": sum(bool(r["near_miss"] and r["false_events"]) for r in routine_rows),
                    "log_ok": sum(bool(r["log_ok"]) for r in routine_rows if r["log_ok"] is not None),
                    "log_n": sum(r["log_ok"] is not None for r in routine_rows)},
        "diary": {"log_entries": len(logs), "by_kind": {k: sum(l["kind"] == k for l in logs) for k in
                                                         sorted({l["kind"] for l in logs})},
                  "deliveries_logged": sum(r["logged"] for r in deliv_rows if r["delivered"]),
                  "deliveries": sum(r["delivered"] for r in deliv_rows),
                  "delivery_qty_ok": sum(r["qty_ok"] for r in deliv_rows if r["delivered"]),
                  "pending_flagged": sum(r["as_event"] or (r["logged"] and r["arrived_ok"]) for r in deliv_rows if not r["delivered"]),
                  "pending": sum(not r["delivered"] for r in deliv_rows),
                  "equipment_logged": sum(r["logged"] for r in equip_rows), "equipment": len(equip_rows),
                  "outage_ok": sum(bool(r["outage_ok"]) for r in equip_rows if r["outage_ok"] is not None),
                  "outages": sum(r["outage_ok"] is not None for r in equip_rows)},
        "progress": {"correct": sum(r["ok"] for r in prog_rows), "total": len(prog_rows)},
        "staffing": staff,
        "messages": {"expected": len(msg_rows), "drafted": sum(r["drafted"] for r in msg_rows),
                     "to_ag": sum(r["to_ag"] for r in msg_rows),
                     "to_ag_drafted": sum(r["drafted"] for r in msg_rows if r["to_ag"]),
                     "non_ag_unsupported": sum(not r["to_ag"] for r in msg_rows),
                     "wrong_to_ag": sum(r["wrong_to_ag"] for r in msg_rows),
                     "must_include": [sum(r["must_include_hit"] for r in msg_rows if r["drafted"]),
                                      sum(r["must_include_n"] for r in msg_rows if r["drafted"])],
                     "documents_to_draft": must_docs},
        "photos": {"available": len(avail), "missing": len(gold.get("photos_missing") or []),
                   "attach_ok": att_got, "attach_want": att_want, "attach_available": att_avail,
                   "unusable_attached": len(unusable & attached), "unusable": len(unusable)},
        "asr": {"n": len(asr_rows), "wer": sum(r["errors"] for r in asr_rows) / max(1, sum(r["n_ref"] for r in asr_rows)),
                "number_recall": sum(r["num_hit"] for r in asr_rows) / max(1, sum(r["num_total"] for r in asr_rows)),
                "lang_ok": sum(r["lang"] == gold["language"] for r in asr_rows)},
        "runtime": runtime,
        "meta": run["meta"],
    }
    detail = {"summary": S, "gold_events": gold_rows, "closes": closes_rows, "routine": routine_rows,
              "system_events": sys_rows, "deliveries": deliv_rows, "equipment": equip_rows, "progress": prog_rows,
              "messages": msg_rows, "asr": asr_rows, "log_entries": logs}
    (a.out / "result.json").write_text(json.dumps(detail, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = to_md(detail)
    (a.out / "summary.md").write_text(md, encoding="utf-8")
    print(md)


def to_md(d: dict) -> str:
    S = d["summary"]
    p = lambda x: "–" if x is None else f"{100 * x:.0f} %"  # noqa: E731
    ok = lambda b: "–" if b is None else ("✓" if b else "✗")  # noqa: E731
    E, R, D, Mg, P, A = S["events"], S["routine"], S["diary"], S["messages"], S["photos"], S["asr"]
    m = S["meta"]
    L = [f"# {m.get('scenario_id')} {m.get('date')} ({m.get('input_language')}) – Foto-zuerst, Ende-zu-Ende", "",
         f"Modus {m.get('mode')} · ASR {m.get('asr_backend')} · Modelle {m.get('models')} · Ausgabe {m.get('output_language')}",
         "", "| Bereich | Ergebnis |", "|---|---|",
         f"| Ereignisse erkannt | {E['detected']}/{E['gold']} ({p(E['recall'])}) · fragmentiert {E['fragmented']} · "
         f"System-Ereignisse {E['system_events']} |",
         f"| Typ / Sphäre / Schreiben (erkannte) | {p(E['type_acc'])} / {p(E['sphere_acc'])} / {p(E['doc_acc'])} |",
         f"| Fortschreibung Vortag · Abschluss (closes) | {E['continued_ok']}/{E['follow_up']} · {E['closes_ok']}/{E['closes']} |",
         f"| **Routine ohne Fehlalarm** | {R['captures'] - R['false_alarm_captures']}/{R['captures']} "
         f"(Beinahe-Fälle als Ereignis: {R['near_miss_false']}/{R['near_miss']}) |",
         f"| **Routine im Bautagebuch (passende Eintragsart)** | {R['log_ok']}/{R['log_n']} · Einträge {D['by_kind']} |",
         f"| Lieferungen erfasst · Menge richtig · ausstehende erkannt | {D['deliveries_logged']}/{D['deliveries']} · "
         f"{D['delivery_qty_ok']}/{D['deliveries']} · {D['pending_flagged']}/{D['pending']} |",
         f"| Geräte erfasst · Ausfall erkannt | {D['equipment_logged']}/{D['equipment']} · {D['outage_ok']}/{D['outages']} |",
         f"| Leistung je Vorgang · Personal gesamt | {S['progress']['correct']}/{S['progress']['total']} · "
         f"{S['staffing']['system_total']} vs. {S['staffing']['gold_total']} {ok(S['staffing']['ok'])} |",
         f"| Nachrichten: an AG entworfen · an Dritte (nicht unterstützt) · fälschlich an AG | "
         f"{Mg['to_ag_drafted']}/{Mg['to_ag']} · {Mg['non_ag_unsupported']} · {Mg['wrong_to_ag']} |",
         f"| Pflichtinhalte in Entwürfen (≈ Schlüsselwörter) | {Mg['must_include'][0]}/{Mg['must_include'][1]} |",
         f"| Fotos: Pflichtanlagen am Ereignis · unbrauchbare angehängt | {P['attach_ok']}/{P['attach_available']} "
         f"(Gold {P['attach_want']}, {P['missing']} Bilder fehlen) · {P['unusable_attached']}/{P['unusable']} |",
         f"| ASR WER · Zahlen · Sprache | {p(A['wer'])} · {p(A['number_recall'])} · {A['lang_ok']}/{A['n']} |",
         f"| **Verarbeitungszeit je Erfassung** (Upload → Ereignis/Tagebuch) | Median {S['runtime']['p50_s']} s · "
         f"p95 {S['runtime']['p95_s']} s · max {S['runtime']['max_s']} s (n={S['runtime']['n']}; "
         f"Sprachnotiz-Median {S['runtime']['p50_voice_s']} s) |", "",
         "## Gold-Ereignisse", "",
         "| Gold | Erf. | Typ | Sphäre | Schreiben | System | Typ | Sphäre | Schreiben | Vortag | Zeit G → S |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in d["gold_events"]:
        L.append(f"| {r['gold']} | {r['capture']} ({r['note']}) | {r['type']} | {r['sphere']} | {r['doc'] or '–'} | "
                 f"{r['sys_event'] or '**nicht erkannt**'}{' (+' + str(r['n_system'] - 1) + ')' if r['n_system'] > 1 else ''} | "
                 f"{ok(r['type_ok'])} {r['sys_type'] or ''} | {ok(r['sphere_ok'])} {r['sys_sphere'] or ''} | "
                 f"{ok(r['doc_ok'])} {r['sys_doc'] or '–'} | {ok(r['continued_ok'])} | "
                 f"{r['start'] or ''}–{r['end'] or ''} → {r['sys_start'] or ''}–{r['sys_end'] or ''} |")
    L += ["", "## Routine-Erfassungen (sollen KEIN Ereignis erzeugen)", "",
          "| Erf. | Zweck | Notiz | Tagebuch | Fehlalarm | Beinahe-Fall |", "|---|---|---|---|---|---|"]
    L += [f"| {r['capture']} | {r['purpose']} | {r['text']} | {ok(r['log_ok'])} {', '.join(r['log_kinds']) or '–'} | "
          f"{', '.join(r['false_events']) or '–'}{' (closes ' + r['closes'] + ')' if r['closes'] else ''} | "
          f"{r['near_miss'] or ''} |" for r in d["routine"]]
    L += ["", "## Lieferungen / Geräte", ""]
    L += [f"- {r['item']} ({r['qty']}, {r['status']}): erfasst {ok(r['logged'])} {r['sys'] or ''} {r['sys_qty'] or ''} · "
          f"Menge {ok(r['qty_ok'])} · Status {ok(r['arrived_ok'])} · Lieferschein {ok(r['note_ok'])}"
          f"{' · als Ereignis' if r['as_event'] else ''}" for r in d["deliveries"]]
    L += [f"- {r['device']}: erfasst {ok(r['logged'])} {r['states']} · Ausfall {r['ausfall'] or '–'} {ok(r['outage_ok'])}"
          for r in d["equipment"]]
    L += ["", "## Nachrichten", ""]
    L += [f"- {r['capture']} {r['type']} → {r['to']}: Entwurf {ok(r['drafted'])} {r['letters']} · Pflichtinhalt "
          f"{r['must_include_hit']}/{r['must_include_n']} · Anlagen {len(r['attach_got'])}/{len(r['attach_want'])}"
          f"{' · **Empfänger falsch (AG)**' if r['wrong_to_ag'] else ''}" for r in d["messages"]]
    L += ["", "## Leistung", ""]
    L += [f"- {r['activity']}: Gold {r['gold']} {r['unit']} · System {r['system']} {ok(r['ok'])}" for r in d["progress"]]
    L += ["", "## ASR je Sprachnotiz", "", "| Notiz | Stimme | Lärm | SNR | WER | Sprache | asr_score |",
          "|---|---|---|---|---|---|---|"]
    L += [f"| {r['file']} | {r['accent'] or '–'} | {r['noise']} | {r['snr_db']} | {100 * r['wer']:.0f} % | {r['lang']} | "
          f"{r['asr_score']} |" for r in d["asr"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
