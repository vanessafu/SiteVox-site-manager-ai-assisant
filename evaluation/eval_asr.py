#!/usr/bin/env python3
"""ASR-Benchmark: WER/CER, Fachbegriff- und Zahlen-Recall, Sprach-ID, Halluzination auf reinem Lärm,
Kalibrierung der Wort-Scores – gruppiert nach Sprache × SNR × Akzent, mit Szenario-Bootstrap-KI.

Manifest (jsonl), eine Zeile je Aufnahme – kompatibel mit scripts/data/audio/sythesize_noise_data.py:
  {"id": "S03_tr_spk2_snr5", "file": "…wav", "text": "<Referenz, menschlich korrigiert>",
   "scenario_id": "S03", "lang": "tr", "speaker": "spk2", "accent": "tr-L1", "snr_db": 5, "noise": "bagger"}
  Reiner Lärm / Stille: "text": "" → zählt für die Halluzinationsrate (Wörter/Minute).

  # live mit der konfigurierten ASR (z. B. SITEVOX_MODE=gpu SITEVOX_ASR_BACKEND=remote über den Tunnel)
  python -m evaluation.eval_asr --manifest data/asr_eval/manifest.jsonl --out outputs/eval/asr_large-v3
  # oder vorhandene Hypothesen auswerten: {"id", "text", "language", "words": [...]} je Zeile
  python -m evaluation.eval_asr --manifest … --hyps hyps.jsonl --out …
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation import metrics as M  # noqa: E402
from sitevox import settings  # noqa: E402


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def default_terms() -> list[str]:
    c = settings.models()["asr"]
    terms = set(c.get("hotwords", []))
    for line in c.get("initial_prompt", "").replace("\n", " ").split(","):
        if line.strip():
            terms.add(line.strip().rstrip("."))
    return sorted(terms)


def item_id(r: dict) -> str:
    return r.get("id") or Path(r["file"]).stem


def run(manifest: list[dict], hyps: dict[str, dict] | None) -> list[dict]:
    from sitevox.understand import asr

    out = []
    for r in manifest:
        iid = item_id(r)
        t0 = time.perf_counter()
        if hyps is not None:
            h = hyps[iid]
        else:
            h = asr.transcribe(Path(r["file"]), language=r.get("force_language"))
        dt = time.perf_counter() - t0
        out.append({"id": iid, "hyp": h, "elapsed_s": dt})
        print(f"{iid:40s} {dt:6.1f}s  {h.get('language')}  {h.get('text', '')[:60]}", flush=True)
    return out


def score(r: dict, h: dict, terms: list[str]) -> dict:
    ref, hyp = r.get("text", ""), h.get("text", "")
    words = [w for s in h.get("segments", []) for w in s.get("words", [])] or h.get("words", [])
    dur = h.get("duration") or r.get("duration")
    row = {"id": item_id(r), "scenario_id": r.get("scenario_id") or Path(r.get("source", r["file"])).stem,
           "lang": r.get("lang"), "snr_db": r.get("snr_db", "clean"), "noise": r.get("noise"),
           "speaker": r.get("speaker"), "accent": r.get("accent"), "ref": ref, "hyp": hyp,
           "lang_pred": h.get("language"), "language_prob": h.get("language_prob"), "duration": dur}
    if not M.tokens(ref):                                   # reiner Lärm → Halluzination
        row.update(noise_only=True, halluc_words=len(M.tokens(hyp)), minutes=(dur or 0) / 60)
        return row
    w, c = M.wer_counts(ref, hyp), M.cer_counts(ref, hyp)
    th, tt, missed = M.term_hits(ref, hyp, terms)
    nh, nt = M.number_hits(ref, hyp)
    row.update(noise_only=False, errors=w["errors"], n_ref=w["n_ref"], sub=w["sub"], dele=w["del"], ins=w["ins"],
               char_errors=c["errors"], n_chars=c["n_ref"], term_hit=th, term_total=tt, term_missed=missed,
               num_hit=nh, num_total=nt, lang_ok=(r.get("lang") == h.get("language")) if r.get("lang") else None,
               word_scores=M.hyp_word_correctness(ref, words))
    return row


def summarize(rows: list[dict]) -> dict:
    speech = [r for r in rows if not r["noise_only"]]
    noise = [r for r in rows if r["noise_only"]]
    S = lambda items: {  # noqa: E731
        "WER": M.cluster_bootstrap(items, M.ratio("errors", "n_ref")),
        "CER": M.cluster_bootstrap(items, M.ratio("char_errors", "n_chars")),
        "term_recall": M.cluster_bootstrap(items, M.ratio("term_hit", "term_total")),
        "number_recall": M.cluster_bootstrap(items, M.ratio("num_hit", "num_total")),
        "lang_id_acc": M.cluster_bootstrap([i for i in items if i["lang_ok"] is not None], M.mean_of("lang_ok")),
        "n": len(items),
    }
    out: dict = {"overall": S(speech)}
    for keys in (("lang",), ("snr_db",), ("lang", "snr_db"), ("accent",), ("noise",)):
        out["by_" + "_x_".join(keys)] = {"|".join(map(str, k)): S(v) for k, v in M.group_by(speech, *keys).items()
                                        if any(x is not None for x in k)}
    pairs = [p for r in speech for p in r["word_scores"]]
    if pairs:
        sc, ok = [p[0] for p in pairs], [p[1] for p in pairs]
        out["word_score_calibration"] = {"auroc_correct_vs_wrong": M.auroc(sc, ok), "ece": M.ece(sc, ok),
                                         "n_words": len(pairs)}
    if noise:
        mins = sum(r["minutes"] for r in noise)
        out["hallucination"] = {"words_per_min": sum(r["halluc_words"] for r in noise) / mins if mins else None,
                                "clips_with_output": sum(r["halluc_words"] > 0 for r in noise) / len(noise),
                                "n_clips": len(noise)}
    missed: dict[str, int] = {}
    for r in speech:
        for t in r["term_missed"]:
            missed[t] = missed.get(t, 0) + 1
    out["most_missed_terms"] = sorted(missed.items(), key=lambda kv: -kv[1])[:15]
    return out


def to_markdown(s: dict) -> str:
    lines = ["# ASR-Benchmark", "", "Werte in %, [95 %-KI, Szenario-Bootstrap]", ""]
    hdr = "| Gruppe | n | WER ↓ | CER ↓ | Fachbegriffe ↑ | Zahlen ↑ | Sprach-ID ↑ |"
    sep = "|---|---|---|---|---|---|---|"

    def row(name, d):
        return (f"| {name} | {d['n']} | {M.fmt_ci(d['WER'])} | {M.fmt_ci(d['CER'])} | {M.fmt_ci(d['term_recall'])} "
                f"| {M.fmt_ci(d['number_recall'])} | {M.fmt_ci(d['lang_id_acc'])} |")
    lines += [hdr, sep, row("gesamt", s["overall"])]
    for key in ("by_lang", "by_snr_db", "by_lang_x_snr_db", "by_accent", "by_noise"):
        for g, d in s.get(key, {}).items():
            lines.append(row(f"{key[3:]}={g}", d))
    if "word_score_calibration" in s:
        c = s["word_score_calibration"]
        lines += ["", f"Wort-Score-Kalibrierung: AUROC {c['auroc_correct_vs_wrong']:.3f}, ECE {c['ece']:.3f} "
                      f"({c['n_words']} Wörter)"]
    if "hallucination" in s:
        h = s["hallucination"]
        lines += [f"Halluzination auf reinem Lärm: {h['words_per_min'] or 0:.1f} Wörter/min, "
                  f"{100 * h['clips_with_output']:.0f} % der Clips mit Ausgabe ({h['n_clips']} Clips)"]
    if s.get("most_missed_terms"):
        lines += ["", "Häufigste verfehlte Fachbegriffe: " + ", ".join(f"{t} ({k})" for t, k in s["most_missed_terms"])]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--hyps", type=Path, help="vorhandene Hypothesen (jsonl mit id) statt live transkribieren")
    ap.add_argument("--terms", type=Path, help="Fachbegriffe, eine Zeile je Begriff (Standard: aus models.toml)")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    manifest = load_jsonl(a.manifest)
    terms = ([t.strip() for t in a.terms.read_text(encoding="utf-8").splitlines() if t.strip()]
             if a.terms else default_terms())
    hyps = {h["id"]: h for h in load_jsonl(a.hyps)} if a.hyps else None
    a.out.mkdir(parents=True, exist_ok=True)
    preds = run(manifest, hyps)
    by_id = {item_id(r): r for r in manifest}
    rows = [score(by_id[p["id"]], p["hyp"], terms) | {"elapsed_s": p["elapsed_s"]} for p in preds]
    with open(a.out / "items.jsonl", "w", encoding="utf-8") as f:
        for r, p in zip(rows, preds):
            f.write(json.dumps({**r, "raw": p["hyp"]}, ensure_ascii=False, default=str) + "\n")
    s = summarize(rows)
    dur = sum(r["duration"] or 0 for r in rows)
    s["rtf"] = sum(r["elapsed_s"] for r in rows) / dur if dur and hyps is None else None
    s["config"] = {k: settings.models()["asr"].get(k) for k in ("backend", "model", "language", "beam_size")}
    (a.out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = to_markdown(s)
    (a.out / "summary.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
