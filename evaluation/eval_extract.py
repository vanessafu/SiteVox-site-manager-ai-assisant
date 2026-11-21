#!/usr/bin/env python3
"""Extraktions- und Entscheidungs-Benchmark auf dem eigenen Szenario-Set.

Misst je Szenario-Variante (Sprache/Sprecher/ASR-Text):
  * Ereignis-Erkennung P/R/F1 (typgenau) + Typ-Verwechslungsmatrix + Macro-F1
  * Slot-Genauigkeit (Uhrzeit, Ressourcen, Attribute wie predecessor_by_owner)
  * Risikosphäre (Regel aus sitevox.engine.sphere auf den extrahierten Attributen)
  * Schreiben-Entscheidung: VERPASSTE Anzeige (teuer: Rechtsverlust) vs. FALSCHE Anzeige getrennt
  * Mengen-/Personalmeldungen, Zitat-Verankerung (Zitat wörtlich im Input?)
  * Konsistenz-Konfidenz (n Stichproben) → ECE + Risk-Coverage
  * Cross-lingual: liefern alle Sprachfassungen eines Szenarios dieselben Entscheidungen?
  * Kontrastpaare (pair_id): beide Hälften korrekt?

Szenario-Format: siehe evaluation/data/scenarios.example.jsonl und evaluation/README.md.

  SITEVOX_MODE=gpu SITEVOX_LLM_API_KEY=… python -m evaluation.eval_extract \\
      --scenarios evaluation/data/scenarios.jsonl --out outputs/eval/extract_qwen3-4b
  # Fehlerfortpflanzung: dieselben Szenarien mit ASR-Text statt Goldtext
  … --text-field text_asr
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation import metrics as M  # noqa: E402
from sitevox import settings, store  # noqa: E402
from sitevox.engine import sphere as sph  # noqa: E402
from sitevox.llm import LLMError  # noqa: E402
from sitevox.understand import asr, extract  # noqa: E402

ATTR_KEYS = ("owner_supplied_material", "predecessor_by_owner", "own_work", "work_started")
DOCS = sph.DOCS


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.lstrip().startswith("//")]


def _hm(t: Optional[str]) -> Optional[int]:
    if not t:
        return None
    try:
        h, m = t.split(":")[:2]
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def decide(le, acts: list[dict], weather_exceptional: Optional[bool]) -> dict:
    """Extrahiertes LLM-Ereignis → Sphäre + empfohlenes Schreiben (dieselben Regeln wie pipeline.py)."""
    attrs = {k: getattr(le, k) for k in ATTR_KEYS}
    act_ids = [a for a in (extract.match_activity(n, acts) for n in le.affected_activities) if a]
    s, _ = sph.rule_sphere(le.type, attrs, weather_exceptional=weather_exceptional)
    rec = sph.recommend(le.type, s, attrs, affects_schedule=bool(act_ids))
    return {"type": le.type, "start_time": le.start_time, "sphere": s, "document": rec.kind,
            "letter": rec.requires_letter, "attrs": attrs, "activity_ids": sorted(act_ids),
            "resources": sorted(r.resource.lower() for r in le.resource_effects),
            "llm_sphere_guess": le.responsible_party_guess, "quotes": le.quotes}


def match_events(gold: list[dict], pred: list[dict]) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """1) gleiche Typen paaren (nächste Uhrzeit), 2) Rest der Reihe nach als Typverwechslung paaren."""
    g_left, p_left, same = set(range(len(gold))), set(range(len(pred))), []
    cands = sorted(((abs((_hm(gold[i].get("start_time")) or 0) - (_hm(pred[j]["start_time"]) or 0)), i, j)
                    for i in range(len(gold)) for j in range(len(pred)) if gold[i]["type"] == pred[j]["type"]))
    for _, i, j in cands:
        if i in g_left and j in p_left:
            same.append((i, j))
            g_left.discard(i)
            p_left.discard(j)
    cross = list(zip(sorted(g_left), sorted(p_left)))
    return same, cross


def gold_doc(g: dict) -> str:
    return g.get("document", "bautagebuch")


def evaluate_item(sc: dict, res: Optional[dict], acts: list[dict], text: str) -> dict:
    gold = sc["gold"]
    g_events = gold.get("events", [])
    row: dict[str, Any] = {"id": sc["id"], "scenario_id": sc.get("scenario_id", sc["id"]), "lang": sc.get("lang"),
                           "pair_id": sc.get("pair_id"), "tags": sc.get("tags", [])}
    if res is None:
        return row | {"schema_fail": True, "pred_events": [], "tp": 0, "fp": 0, "fn": len(g_events),
                      "letters_gold": sorted({gold_doc(g) for g in g_events if DOCS[gold_doc(g)]["letter"]}),
                      "letters_pred": [], "missed_letter": 0, "false_letter": 0, "decision_ok": False}
    wx = sc.get("weather_exceptional")
    main, samples = res["main"], res["samples"]
    p_events = [decide(le, acts, wx) for le in main.events]
    s_events = [[decide(le, acts, wx) for le in s.events] for s in samples]
    same, cross = match_events(g_events, p_events)

    slots = defaultdict(lambda: [0, 0])                      # Feld → [richtig, gesamt]
    type_pairs = []
    for i, j in same + cross:
        g, p = g_events[i], p_events[j]
        type_pairs.append((g["type"], p["type"]))
        for key in ("sphere", "document"):
            want = g.get(key) if key != "document" else gold_doc(g)
            if want is not None:
                slots[key][0] += p[key] == want
                slots[key][1] += 1
    for i, j in same:
        g, p = g_events[i], p_events[j]
        if g.get("start_time"):
            slots["start_time"][0] += _hm(g["start_time"]) == _hm(p["start_time"])
            slots["start_time"][1] += 1
        for k, v in (g.get("attrs") or {}).items():
            slots[f"attr.{k}"][0] += p["attrs"].get(k) == v
            slots[f"attr.{k}"][1] += 1
        if g.get("resources"):  # Gold-Ressource darf Alternativen haben: "Bagger|excavator|koparka"
            alts = [{a.strip().lower() for a in x.split("|")} for x in g["resources"]]
            hit = len(alts) == len(p["resources"]) and all(any(r in a or any(t in r for t in a)
                                                               for r in p["resources"]) for a in alts)
            slots["resources"][0] += hit
            slots["resources"][1] += 1
    for i in range(len(g_events)):
        if i not in {a for a, _ in same + cross}:
            type_pairs.append((g_events[i]["type"], "∅"))
    for j in range(len(p_events)):
        if j not in {b for _, b in same + cross}:
            type_pairs.append(("∅", p_events[j]["type"]))

    # Schreiben-Entscheidung auf Szenario-Ebene (Menge der nötigen Schreiben an den AG)
    lg = sorted({gold_doc(g) for g in g_events if DOCS[gold_doc(g)]["letter"]})
    lp = sorted({p["document"] for p in p_events if p["letter"]})

    # Mengen & Personal
    def prog_key(x):
        aid = extract.match_activity(x["activity"] if isinstance(x, dict) else x.activity, acts) or (
            x["activity"] if isinstance(x, dict) else x.activity).lower()
        q = x["quantity"] if isinstance(x, dict) else x.quantity
        return (aid, f"{float(q):g}")
    gp = [prog_key(x) for x in gold.get("progress", [])]
    pp = [prog_key(x) for x in main.progress]
    prog_hit = sum(min(gp.count(k), pp.count(k)) for k in set(gp))
    gs = [(x.get("present"), x.get("absent")) for x in gold.get("staffing", [])]
    ps = [(x.present, x.absent) for x in main.staffing]
    staff_hit = sum(any(p[0] == g[0] and (g[1] is None or p[1] == g[1]) for p in ps) for g in gs)

    # Zitat-Verankerung
    tr = asr._from_text(text)
    quotes = [q for p in p_events for q in p["quotes"]]
    grounded = sum(asr.locate_quote(tr, q, min_ratio=0.8) is not None for q in quotes)

    # Konsistenz-Konfidenz je vorhergesagtem Ereignis: Anteil der Stichproben mit demselben (Typ, Schreiben)
    conf_pairs = []
    tp_pred = {j for _, j in same}
    for j, p in enumerate(p_events):
        agree = [any(q["type"] == p["type"] and q["document"] == p["document"] for q in se) for se in s_events]
        c = sum(agree) / len(agree) if agree else None
        g_doc_ok = any(j == jj and p["document"] == gold_doc(g_events[ii]) for ii, jj in same)
        if c is not None:
            conf_pairs.append((c, j in tp_pred and g_doc_ok))

    return row | {
        "schema_fail": False, "pred_events": p_events,
        "tp": len(same), "fp": len(p_events) - len(same), "fn": len(g_events) - len(same),
        "n_gold": len(g_events), "type_pairs": type_pairs, "slots": {k: tuple(v) for k, v in slots.items()},
        "letters_gold": lg, "letters_pred": lp,
        "missed_letter": len(set(lg) - set(lp)), "false_letter": len(set(lp) - set(lg)), "decision_ok": lg == lp,
        "needs_letter": bool(lg), "prog_hit": prog_hit, "prog_gold": len(gp), "prog_pred": len(pp),
        "staff_hit": staff_hit, "staff_gold": len(gs), "quotes": len(quotes), "quotes_grounded": grounded,
        "llm_sphere_disagree": sum(p["llm_sphere_guess"] not in ("unklar", p["sphere"]) for p in p_events),
        "conf_pairs": conf_pairs,
    }


def summarize(rows: list[dict]) -> dict:
    B = M.cluster_bootstrap
    ok = [r for r in rows if not r["schema_fail"]]

    def f1(items):
        return M.prf(sum(i["tp"] for i in items), sum(i["fp"] for i in items), sum(i["fn"] for i in items))["f1"]

    def slot(name):
        def f(items):
            got = [i["slots"][name] for i in items if name in i.get("slots", {})]
            tot = sum(t for _, t in got)
            return sum(c for c, _ in got) / tot if tot else float("nan")
        return f
    slot_names = sorted({k for r in ok for k in r["slots"]})
    pairs = [p for r in ok for p in r["type_pairs"]]
    typed = [p for p in pairs if "∅" not in p]
    need = [r for r in rows if r.get("needs_letter")]
    no_need = [r for r in rows if not r.get("needs_letter") and not r["schema_fail"]]
    s: dict[str, Any] = {
        "n_items": len(rows), "n_scenarios": len({r["scenario_id"] for r in rows}),
        "schema_fail_rate": B(rows, M.mean_of("schema_fail")),
        "event_f1": B(rows, f1),
        "event_precision": B(rows, lambda it: M.prf(sum(i["tp"] for i in it), sum(i["fp"] for i in it), 0)["precision"]),
        "event_recall": B(rows, lambda it: M.prf(sum(i["tp"] for i in it), 0, sum(i["fn"] for i in it))["recall"]),
        "type_macro_f1_on_paired": M.macro_f1(typed) if typed else float("nan"),
        "type_confusion": M.confusion(pairs),
        "slots": {k: B(ok, slot(k)) for k in slot_names},
        "decision_exact": B(rows, M.mean_of("decision_ok")),
        # die beiden Fehlerarten getrennt – verpasste Anzeige ist der teure Fehler
        "missed_letter_rate": B(need, lambda it: sum(i["missed_letter"] for i in it) /
                                max(1, sum(len(i["letters_gold"]) for i in it))) if need else None,
        "false_letter_rate_on_no_letter_items": B(no_need, lambda it: sum(i["false_letter"] > 0 for i in it) /
                                                  max(1, len(it))) if no_need else None,
        "progress_recall": B(ok, M.ratio("prog_hit", "prog_gold")),
        "staffing_recall": B(ok, M.ratio("staff_hit", "staff_gold")),
        "quote_grounding": B(ok, M.ratio("quotes_grounded", "quotes")),
    }
    cp = [p for r in ok for p in r["conf_pairs"]]
    if cp:
        rc = M.risk_coverage([c for c, _ in cp], [y for _, y in cp])
        s["confidence"] = {"ece": M.ece([c for c, _ in cp], [y for _, y in cp]), "aurc": rc["aurc"],
                           "auroc": M.auroc([c for c, _ in cp], [y for _, y in cp]), "n": len(cp),
                           "risk_at_coverage": {f"{int(cov * 100)}%": next((p["risk"] for p in rc["curve"]
                                                                            if p["coverage"] >= cov), None)
                                                for cov in (0.5, 0.8, 1.0)}}
    # Cross-lingual: identische Entscheidungen über alle Sprachfassungen eines Szenarios
    by_sc = M.group_by(ok, "scenario_id")
    multi = {k: v for k, v in by_sc.items() if len({r["lang"] for r in v}) > 1}
    if multi:
        sig = lambda r: tuple(sorted((p["type"], p["document"]) for p in r["pred_events"]))  # noqa: E731
        s["crosslingual_consistency"] = {"all_langs_identical": sum(len({sig(r) for r in v}) == 1
                                                                    for v in multi.values()) / len(multi),
                                         "n_scenarios": len(multi)}
    pairs_by = M.group_by([r for r in rows if r.get("pair_id")], "pair_id")
    if pairs_by:
        s["contrastive_pairs_both_correct"] = {"value": sum(all(r["decision_ok"] for r in v)
                                                            for v in pairs_by.values()) / len(pairs_by),
                                               "n_pairs": len(pairs_by)}
    s["by_lang"] = {str(k[0]): {"event_f1": B(v, f1), "decision_exact": B(v, M.mean_of("decision_ok")), "n": len(v)}
                    for k, v in M.group_by(rows, "lang").items()}
    return s


def to_markdown(s: dict) -> str:
    F = M.fmt_ci
    L = ["# Extraktion & Entscheidung", "", f"{s['n_items']} Items aus {s['n_scenarios']} Szenarien; "
         "Werte in %, [95 %-KI, Szenario-Bootstrap]", "",
         "| Metrik | Wert |", "|---|---|",
         f"| Ereignis-F1 (typgenau) | {F(s['event_f1'])} |",
         f"| Precision / Recall | {F(s['event_precision'])} / {F(s['event_recall'])} |",
         f"| Typ-Macro-F1 (gepaarte Ereignisse) | {100 * s['type_macro_f1_on_paired']:.1f} |",
         f"| **Schreiben-Entscheidung exakt** | {F(s['decision_exact'])} |"]
    if s.get("missed_letter_rate"):
        L.append(f"| **Verpasste Anzeige** ↓ (Anteil nötiger Schreiben) | {F(s['missed_letter_rate'])} |")
    if s.get("false_letter_rate_on_no_letter_items"):
        L.append(f"| Falsche Anzeige ↓ (Items ohne nötiges Schreiben) | {F(s['false_letter_rate_on_no_letter_items'])} |")
    L += [f"| Mengen-Recall | {F(s['progress_recall'])} |", f"| Personal-Recall | {F(s['staffing_recall'])} |",
          f"| Zitat-Verankerung | {F(s['quote_grounding'])} |", f"| Schema-Fehler ↓ | {F(s['schema_fail_rate'])} |"]
    for k, v in s["slots"].items():
        L.append(f"| Slot {k} | {F(v)} |")
    if "crosslingual_consistency" in s:
        c = s["crosslingual_consistency"]
        L.append(f"| Cross-lingual identisch | {100 * c['all_langs_identical']:.1f} ({c['n_scenarios']} Szen.) |")
    if "contrastive_pairs_both_correct" in s:
        c = s["contrastive_pairs_both_correct"]
        L.append(f"| Kontrastpaare beide korrekt | {100 * c['value']:.1f} ({c['n_pairs']} Paare) |")
    if "confidence" in s:
        c = s["confidence"]
        L.append(f"| Konfidenz: ECE / AURC / AUROC | {c['ece']:.3f} / {c['aurc']:.3f} / {c['auroc']:.3f} (n={c['n']}) |")
    L += ["", "| Sprache | n | Ereignis-F1 | Entscheidung exakt |", "|---|---|---|---|"]
    for lang, d in s["by_lang"].items():
        L.append(f"| {lang} | {d['n']} | {F(d['event_f1'])} | {F(d['decision_exact'])} |")
    L += ["", "Typ-Verwechslung (Gold → Vorhersage; ∅ = nicht erkannt / zusätzlich):", ""]
    for g, row in sorted(s["type_confusion"].items()):
        L.append(f"- {g}: " + ", ".join(f"{p} ×{k}" for p, k in sorted(row.items(), key=lambda kv: -kv[1])))
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", required=True, type=Path)
    ap.add_argument("--project", default="BV-RIEM")
    ap.add_argument("--text-field", default="text", help="text (Gold) | text_asr (Fehlerfortpflanzung)")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    acts = store.activities(a.project)
    if not acts:
        sys.exit("Keine Vorgänge in der DB – zuerst scripts/seed_demo.py (bzw. eigenes Projekt) laden.")
    a.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for sc in load_jsonl(a.scenarios):
        text = sc.get(a.text_field) or sc["text"]
        try:
            res = extract.extract(text, project_id=a.project, date=sc.get("date", "2026-11-20"),
                                  time=sc.get("time", "08:00"), source=sc.get("source", "audio"), acts=acts)
        except LLMError as e:
            print(f"{sc['id']}: Schema-Fehler {e}", file=sys.stderr)
            res = None
        r = evaluate_item(sc, res, acts, text)
        rows.append(r)
        print(f"{r['id']:24s} tp={r['tp']} fp={r['fp']} fn={r['fn']} gold={r['letters_gold']} "
              f"pred={r['letters_pred']}", flush=True)
    with open(a.out / "items.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    s = summarize(rows)
    s["config"] = {"mode": settings.mode(), "model": settings.models()["llm"]["extractor"]["model"],
                   "text_field": a.text_field}
    (a.out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = to_markdown(s)
    (a.out / "summary.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
