#!/usr/bin/env python3
"""Ende-zu-Ende-Auswertung eines simulierten Bautags gegen das Gold-Szenario.

  python -m evaluation.eval_scenario --run <SITEVOX_DATA>/run_output.json \
      --inputs data/raw/scenario_SCN-RIEM-0016_en --scenario data/demo/scenario/scenario_SCN-RIEM-0016_en.json \
      --out outputs/eval/scenario_SCN-RIEM-0016_en

Zuordnung System-Ereignis → Gold-Ereignis NUR über die Belege: Ereignis → Belege → Erfassung → Eingabedatei →
gold.json (welche Gold-Ereignisse diese Eingabe trägt). Das System sieht gold.json nie.

Kennzahlen
  Ereignisse   Erkennung (Recall je Gold-Ereignis), Typ, Sphäre, Fehlalarme (Ereignis aus Routine/Beinahe-Fall),
               Fragmentierung (ein Gold-Ereignis → mehrere System-Ereignisse), Zeiten (Beginn/Ende)
  Schreiben    richtig empfohlen (documents_to_draft) · fälschlich empfohlen (documents_must_not_draft) · Entwürfe
               mit offenen Prüfstellen
  Fotos        Zuordnung des Fotos zum richtigen Ereignis (Foto-Name und -Zeit verraten nichts über das Ereignis)
  ASR          WER je Memo (Rauschart/SNR), Sprach-ID
  Bautagebuch  Leistungen je Vorgang, Personal je Kolonne
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
INCIDENT_KINDS = {"incident", "follow_up"}


def gold_doc_kind(label: dict) -> str | None:
    doc, basis = (label.get("document") or ""), " ".join(label.get("basis") or [])
    if not doc:
        return None
    d = doc.lower()
    if "behinderung" in d:
        return "behinderungsanzeige"
    if "bedenken" in d:
        return "bedenkenanzeige"
    if "wiederaufnahme" in d:
        return "wiederaufnahme"  # Mitteilung nach § 6 Abs. 3 VOB/B – kennt das System (noch) nicht
    if "mehrkosten" in d or "nachtrag" in d:
        return "nachtragsankuendigung" if "Abs. 5" in basis or "Abs. 5" in doc else "mehrkostenankuendigung"
    return d


def hhmm(x) -> str | None:
    if not x:
        return None
    m = re.search(r"(\d{2}):(\d{2})", str(x))
    return f"{m.group(1)}:{m.group(2)}" if m else None


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
    gev = {e["event_id"]: e for e in sc["events"]}
    a.out.mkdir(parents=True, exist_ok=True)

    cap2file = {i["capture_id"]: i["file"] for i in run["inputs"]}
    file2gold = {f: g["events"] for f, g in gold["inputs"].items()}

    # ------------------------------------------------------------------ System-Ereignis → Gold-Ereignis
    matches, sys_rows = defaultdict(list), []
    for e in run["events"]:
        files = sorted({cap2file.get(run["evidence_capture"].get(x)) for x in e["evidence"]} - {None})
        votes = defaultdict(int)
        for f in files:
            for g in file2gold.get(f, []):
                votes[g] += 1
        # bevorzugt Vorfälle; bei Gleichstand der passende Typ
        cand = sorted(votes, key=lambda g: (-(gev[g]["kind"] in INCIDENT_KINDS), -votes[g],
                                            -(TYPE_MAP.get(gev[g]["type"], gev[g]["type"]) == e["type"])))
        g = cand[0] if cand else None
        row = {"event_id": e["event_id"], "type": e["type"], "sphere": e["sphere"], "start": hhmm(e.get("start")),
               "end": hhmm(e.get("end")), "doc": e["recommended_document"]["kind"],
               "requires_letter": e["recommended_document"].get("requires_letter"), "files": files,
               "gold": g, "gold_kind": gev[g]["kind"] if g else None, "description": e.get("description"),
               "date": e["date"], "letter_id": e.get("letter_id")}
        sys_rows.append(row)
        if g:
            matches[g].append(row)

    gold_rows = []
    for gid, g in gev.items():
        if g["kind"] not in INCIDENT_KINDS:
            continue
        ms = matches.get(gid, [])
        gt = TYPE_MAP.get(g["type"], g["type"])
        best = next((m for m in ms if m["type"] == gt), ms[0] if ms else None)
        gdoc = gold_doc_kind(g["label"])
        gold_rows.append({
            "gold": gid, "summary": g["summary"], "kind": g["kind"], "type": gt, "sphere": g["label"]["sphere"],
            "doc": gdoc, "start": hhmm((g.get("time") or {}).get("start")), "end": hhmm((g.get("time") or {}).get("end")),
            "detected": bool(ms), "n_system": len(ms), "sys_event": best["event_id"] if best else None,
            "sys_type": best["type"] if best else None, "type_ok": bool(best and best["type"] == gt),
            "sys_sphere": best["sphere"] if best else None, "sphere_ok": bool(best and best["sphere"] == g["label"]["sphere"]),
            "sys_doc": (best["doc"] if best and best["requires_letter"] else None) if best else None,
            "doc_ok": bool(best and ((best["doc"] if best["requires_letter"] else None) == gdoc)),
            "sys_start": best["start"] if best else None, "sys_end": best["end"] if best else None,
        })
    false_alarms = [r for r in sys_rows if r["gold"] is None or r["gold_kind"] not in INCIDENT_KINDS]

    # ------------------------------------------------------------------ Schreiben
    must = {d["event"] for d in sc["expected_report"]["documents_to_draft"]}
    must_not = {d["event"] for d in sc["expected_report"]["documents_must_not_draft"]}
    letter_by_event = {l["event_id"]: l for l in run["letters"] if l}
    doc_rows = []
    for gid in sorted(must | must_not):
        ms = matches.get(gid, [])
        recommended = [m for m in ms if m["requires_letter"]]
        doc_rows.append({"gold": gid, "should_draft": gid in must, "gold_doc": gold_doc_kind(gev[gid]["label"]),
                         "system_letter": [f"{m['doc']}" for m in recommended],
                         "ok": (bool(recommended) == (gid in must)) and
                               (gid not in must or any(m["doc"] == gold_doc_kind(gev[gid]["label"]) for m in recommended))})
    letters = [{"letter_id": l["letter_id"], "kind": l["kind"], "event": l["event_id"],
                "open_issues": sum(i["status"] in ("unverified", "needs_confirmation") for i in l["issues"]),
                "sentences": sum(len(v) for v in l["sections"]["llm"].values())} for l in run["letters"] if l]

    # ------------------------------------------------------------------ Fotos
    caps = {c["capture_id"]: c for c in run["captures"]}
    photo_rows = []
    for i in run["inputs"]:
        if i["kind"] != "photo":
            continue
        want = {g for g in file2gold[i["file"]] if gev[g]["kind"] in INCIDENT_KINDS}
        got_sys = caps[i["capture_id"]]["event_ids"] or []
        got = {r["gold"] for r in sys_rows if r["event_id"] in got_sys and r["gold"] in gev and
               gev[r["gold"]]["kind"] in INCIDENT_KINDS}
        v = caps[i["capture_id"]].get("vision") or {}
        photo_rows.append({"file": i["file"], "input_id": gold["photos"].get(Path(i["file"]).name), "want": sorted(want),
                           "got": sorted(got), "sys_events": got_sys, "ok": got == want,
                           "question": (caps[i["capture_id"]].get("followup") or {}).get("question"),
                           "vision_summary": v.get("summary"),
                           "observations": [f"{o['category']}/{o['subtype']}" for o in v.get("observations", [])]})

    # ------------------------------------------------------------------ ASR
    asr_rows = []
    for i in run["inputs"]:
        if i["kind"] != "audio":
            continue
        g, c = gold["inputs"][i["file"]], caps[i["capture_id"]]
        hyp = c.get("transcript_text") or ""
        w = M.wer_counts(M.canonical(g["text"]), M.canonical(hyp))  # Uhrzeit/Datum/Dezimal-Schreibweise vereinheitlicht
        nh, nt = M.number_hits(g["text"], hyp)
        asr_rows.append({"file": i["file"], "noise": g["noise"], "snr_db": g["snr_db"], "wer": w["errors"] / max(1, w["n_ref"]),
                         "errors": w["errors"], "n_ref": w["n_ref"], "num_hit": nh, "num_total": nt,
                         "lang": c.get("language"), "asr_score": c.get("asr_score"), "ref": g["text"], "hyp": hyp,
                         "voice": g.get("voice"), "accent": g.get("accent")})

    # ------------------------------------------------------------------ Bautagebuch: Leistung, Personal
    prog = {p["activity_id"]: p["qty"] for p in run["progress"]}
    prog_rows = [{"activity": r["vorgang"], "gold": r["ist"], "system": prog.get(r["vorgang"]), "unit": r["einheit"],
                  "ok": prog.get(r["vorgang"]) is not None and abs(prog[r["vorgang"]] - r["ist"]) <= 0.01 * max(1, r["ist"])}
                 for r in sc["expected_report"]["5_leistungen"]]
    staff = {s["crew"]: s for s in run["staffing"]}
    staff_rows = []
    for r in sc["expected_report"]["2_personal"] + [{"crew": "Gesamt", **sc["expected_report"]["2_personal_summe"]}]:
        s = next((v for k, v in staff.items() if k.lower().split()[-1] in r["crew"].lower()
                  or r["crew"].lower().split()[-1] in k.lower()), None)
        staff_rows.append({"crew": r["crew"], "gold_present": r["ist"], "gold_planned": r["soll"],
                           "system": s["present"] if s else None, "system_crew": s["crew"] if s else None,
                           "ok": bool(s and s["present"] == r["ist"])})

    # ------------------------------------------------------------------ Zusammenfassung
    n = len(gold_rows)
    det = [r for r in gold_rows if r["detected"]]
    S = {
        "events": {"gold": n, "detected": len(det), "recall": len(det) / n if n else None,
                   "type_acc": sum(r["type_ok"] for r in det) / len(det) if det else None,
                   "sphere_acc": sum(r["sphere_ok"] for r in det) / len(det) if det else None,
                   "doc_acc": sum(r["doc_ok"] for r in det) / len(det) if det else None,
                   "false_alarms": len(false_alarms), "fragmented": sum(r["n_system"] > 1 for r in gold_rows),
                   "system_events": len(sys_rows)},
        "documents": {"correct": sum(r["ok"] for r in doc_rows), "total": len(doc_rows),
                      "missed_required": [r["gold"] for r in doc_rows if r["should_draft"] and not r["system_letter"]],
                      "wrongly_recommended": [r["gold"] for r in doc_rows if not r["should_draft"] and r["system_letter"]],
                      "letters": letters},
        "photos": {"correct": sum(r["ok"] for r in photo_rows), "total": len(photo_rows)},
        "asr": {"wer": sum(r["errors"] for r in asr_rows) / max(1, sum(r["n_ref"] for r in asr_rows)),
                "number_recall": sum(r["num_hit"] for r in asr_rows) / max(1, sum(r["num_total"] for r in asr_rows)),
                "lang_ok": sum(r["lang"] == gold["language"] for r in asr_rows), "n": len(asr_rows)},
        "progress": {"correct": sum(r["ok"] for r in prog_rows), "total": len(prog_rows)},
        "staffing": {"correct": sum(r["ok"] for r in staff_rows), "total": len(staff_rows)},
        "meta": run["meta"],
    }
    detail = {"summary": S, "gold_events": gold_rows, "system_events": sys_rows, "false_alarms": false_alarms,
              "documents": doc_rows, "photos": photo_rows, "asr": asr_rows, "progress": prog_rows, "staffing": staff_rows}
    (a.out / "result.json").write_text(json.dumps(detail, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = to_md(detail)
    (a.out / "summary.md").write_text(md, encoding="utf-8")
    print(md)


def to_md(d: dict) -> str:
    S = d["summary"]
    p = lambda x: "–" if x is None else f"{100 * x:.0f} %"  # noqa: E731
    L = [f"# Szenario {S['meta'].get('scenario_id')} ({S['meta'].get('input_language')}) – Ende-zu-Ende", "",
         f"Modus {S['meta'].get('mode')} · ASR {S['meta'].get('asr_backend')} · Modelle {S['meta'].get('models')} · "
         f"Ausgabesprache {S['meta'].get('output_language')}", "",
         "| Bereich | Ergebnis |", "|---|---|",
         f"| Ereignisse erkannt | {S['events']['detected']}/{S['events']['gold']} ({p(S['events']['recall'])}) |",
         f"| Typ / Sphäre / Schreiben richtig (erkannte) | {p(S['events']['type_acc'])} / {p(S['events']['sphere_acc'])} / "
         f"{p(S['events']['doc_acc'])} |",
         f"| Fehlalarme · fragmentierte Ereignisse | {S['events']['false_alarms']} · {S['events']['fragmented']} "
         f"(System-Ereignisse gesamt {S['events']['system_events']}) |",
         f"| Schreiben-Entscheidung richtig | {S['documents']['correct']}/{S['documents']['total']} · fehlend "
         f"{S['documents']['missed_required']} · fälschlich {S['documents']['wrongly_recommended']} |",
         f"| Fotos richtig zugeordnet | {S['photos']['correct']}/{S['photos']['total']} |",
         f"| ASR WER · Zahlen-Recall · Sprache richtig | {p(S['asr']['wer'])} · {p(S['asr']['number_recall'])} · "
         f"{S['asr']['lang_ok']}/{S['asr']['n']} |",
         f"| Leistungen richtig · Personal richtig | {S['progress']['correct']}/{S['progress']['total']} · "
         f"{S['staffing']['correct']}/{S['staffing']['total']} |", "",
         "## Gold-Ereignisse", "", "| Gold | Typ | Sphäre | Schreiben | System | Typ | Sphäre | Schreiben | Zeit (Gold → System) |",
         "|---|---|---|---|---|---|---|---|---|"]
    ok = lambda b: "✓" if b else "✗"  # noqa: E731
    for r in d["gold_events"]:
        L.append(f"| {r['gold']} {r['summary'][:45]} | {r['type']} | {r['sphere']} | {r['doc'] or '–'} | "
                 f"{r['sys_event'] or '**nicht erkannt**'}{' (+' + str(r['n_system'] - 1) + ')' if r['n_system'] > 1 else ''} | "
                 f"{ok(r['type_ok'])} {r['sys_type'] or ''} | {ok(r['sphere_ok'])} {r['sys_sphere'] or ''} | "
                 f"{ok(r['doc_ok'])} {r['sys_doc'] or '–'} | {r['start']}–{r['end'] or ''} → {r['sys_start']}–{r['sys_end'] or ''} |")
    if d["false_alarms"]:
        L += ["", "## Fehlalarme (Ereignis ohne Gold-Vorfall)", ""]
        L += [f"- {r['event_id']} {r['type']} ({r['sphere']}, {r['doc']}) aus {r['files']} → Gold {r['gold']}: "
              f"{(r['description'] or '')[:100]}" for r in d["false_alarms"]]
    L += ["", "## Fotos", "", "| Foto | Gold | System | Beobachtungen | Rückfrage |", "|---|---|---|---|---|"]
    L += [f"| {r['file']} ({r['input_id']}) | {r['want']} | {ok(r['ok'])} {r['got']} | {', '.join(r['observations'])} | "
          f"{(r['question'] or '')[:70]} |" for r in d["photos"]]
    L += ["", "## ASR je Memo", "", "| Memo | Stimme | Lärm | SNR | WER | Sprache | asr_score |",
          "|---|---|---|---|---|---|---|"]
    L += [f"| {r['file']} | {r.get('accent') or '–'} | {r['noise']} | {r['snr_db']} | {100 * r['wer']:.0f} % | "
          f"{r['lang']} | {r['asr_score']} |" for r in d["asr"]]
    L += ["", "## Leistungen / Personal", ""]
    L += [f"- {r['activity']}: Gold {r['gold']} {r['unit']} · System {r['system']} {ok(r['ok'])}" for r in d["progress"]]
    L += [f"- {r['crew']}: Gold {r['gold_present']}/{r['gold_planned']} · System {r['system']} ({r['system_crew']}) "
          f"{ok(r['ok'])}" for r in d["staffing"]]
    L += ["", "## Schreiben", ""]
    L += [f"- {r['gold']}: {'soll' if r['should_draft'] else 'darf nicht'} ({r['gold_doc'] or '–'}) · System "
          f"{r['system_letter'] or '–'} {ok(r['ok'])}" for r in d["documents"]]
    L += [f"- Entwurf {x['letter_id']} {x['kind']} ({x['event']}): {x['sentences']} Sätze, {x['open_issues']} offene "
          f"Prüfstellen" for x in d["summary"]["documents"]["letters"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
