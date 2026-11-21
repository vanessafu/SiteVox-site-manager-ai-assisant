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


NUM_KINDS = ("time", "date", "quantity", "number")
_nk = lambda k: "other_number" if k == "number" else k  # noqa: E731


def accent_group(r: dict) -> str | None:
    """L1 (Muttersprache = Sprache der Aufnahme) · L2 (echte Sprecher:in mit anderem L1) · L2-clone (TTS-Stimmklon)
    · tts (Studio-Stimme, neutral). accent "pl-L1" = Erstsprache Polnisch."""
    a = r.get("accent")
    if not a:
        return None
    if a == "tts":
        return "tts"
    if a.endswith("-clone"):
        return "L2-clone"
    l1 = a.split("-")[0]
    return "L1" if l1 == (r.get("lang") or "de") else "L2"


def score(r: dict, h: dict, terms: list[str]) -> dict:
    ref, hyp = r.get("text", ""), h.get("text", "")
    words = [w for s in h.get("segments", []) for w in s.get("words", [])] or h.get("words", [])
    dur = h.get("duration") or r.get("duration")
    row = {"id": item_id(r), "scenario_id": r.get("scenario_id") or Path(r.get("source", r["file"])).stem,
           "lang": r.get("lang"), "snr_db": r.get("snr_db", "clean"), "noise": r.get("noise"),
           "speaker": r.get("speaker"), "accent": r.get("accent"), "accent_group": accent_group(r),
           "source_kind": "tts" if r.get("tts_model") else "real", "ref": ref, "hyp": hyp,
           "lang_pred": h.get("language"), "language_prob": h.get("language_prob"), "duration": dur}
    if not M.tokens(ref):                                   # reiner Lärm → Halluzination
        row.update(noise_only=True, halluc_words=len(M.tokens(hyp)), minutes=(dur or 0) / 60)
        return row
    w, c = M.wer_counts(ref, hyp), M.cer_counts(ref, hyp)
    th, tt, missed = M.term_hits(ref, hyp, terms)
    nh, nt = M.number_hits(ref, hyp)
    for kind in NUM_KINDS:
        row[f"{kind}_hit"], row[f"{kind}_total"] = M.numeric_hits(ref, hyp).get(kind, (0, 0))
    row.update(noise_only=False, errors=w["errors"], n_ref=w["n_ref"], sub=w["sub"], dele=w["del"], ins=w["ins"],
               char_errors=c["errors"], n_chars=c["n_ref"], term_hit=th, term_total=tt, term_missed=missed,
               num_hit=nh, num_total=nt, lang_ok=(r.get("lang") == h.get("language")) if r.get("lang") else None,
               word_scores=M.hyp_word_correctness(ref, words))
    return row


GROUPINGS = (("lang",), ("snr_db",), ("lang", "snr_db"), ("accent_group",), ("accent_group", "snr_db"),
             ("lang", "snr_db", "accent_group"), ("source_kind",), ("source_kind", "snr_db"), ("accent",), ("noise",))


def calibration(rows: list[dict]) -> dict | None:
    pairs = [p for r in rows for p in r["word_scores"]]
    if not pairs or len({p[1] for p in pairs}) < 2:
        return None
    sc, ok = [p[0] for p in pairs], [p[1] for p in pairs]
    return {"auroc_correct_vs_wrong": M.auroc(sc, ok), "ece": M.ece(sc, ok), "n_words": len(pairs),
            "word_acc": sum(ok) / len(ok)}


def latency(rows: list[dict]) -> dict:
    """Pro Clip (ohne den ersten Aufruf = Modell-Laden/Warm-up). RTF = Rechenzeit / Audiodauer."""
    r = sorted(rows[1:] if len(rows) > 1 else rows, key=lambda x: x["elapsed_s"])
    if not r:
        return {}
    q = lambda p: r[min(len(r) - 1, int(p * len(r)))]["elapsed_s"]  # noqa: E731
    dur = sum(x["duration"] or 0 for x in r)
    rtfs = sorted(x["elapsed_s"] / x["duration"] for x in r if x["duration"])
    return {"rtf": sum(x["elapsed_s"] for x in r) / dur if dur else None,
            "rtf_p95": rtfs[min(len(rtfs) - 1, int(0.95 * len(rtfs)))] if rtfs else None,
            "latency_p50_s": q(0.5), "latency_p95_s": q(0.95), "latency_max_s": r[-1]["elapsed_s"],
            "warmup_s": rows[0]["elapsed_s"], "audio_s_mean": dur / len(r), "n": len(r)}


def summarize(rows: list[dict]) -> dict:
    speech = [r for r in rows if not r["noise_only"]]
    noise = [r for r in rows if r["noise_only"]]
    S = lambda items: {  # noqa: E731
        "WER": M.cluster_bootstrap(items, M.ratio("errors", "n_ref")),
        "CER": M.cluster_bootstrap(items, M.ratio("char_errors", "n_chars")),
        "term_recall": M.cluster_bootstrap(items, M.ratio("term_hit", "term_total")),
        "number_recall": M.cluster_bootstrap(items, M.ratio("num_hit", "num_total")),
        # je Art; "number" (sonstige Zahl) als other_number_*, damit number_recall (alle Zahlen) erhalten bleibt
        **{f"{_nk(k)}_recall": M.cluster_bootstrap(items, M.ratio(f"{k}_hit", f"{k}_total")) for k in NUM_KINDS},
        "n_terms": sum(i["term_total"] for i in items),
        **{f"n_{_nk(k)}": sum(i[f"{k}_total"] for i in items) for k in NUM_KINDS},
        "lang_id_acc": M.cluster_bootstrap([i for i in items if i["lang_ok"] is not None], M.mean_of("lang_ok")),
        "n": len(items),
    }
    out: dict = {"overall": S(speech)}
    for keys in GROUPINGS:
        out["by_" + "_x_".join(keys)] = {"|".join(map(str, k)): S(v) for k, v in M.group_by(speech, *keys).items()
                                        if any(x is not None for x in k)}
    if (c := calibration(speech)) is not None:
        out["word_score_calibration"] = c
        out["word_score_calibration_by_snr_db"] = {
            str(k[0]): cc for k, v in M.group_by(speech, "snr_db").items() if (cc := calibration(v)) is not None}
        out["word_score_calibration_by_source_kind"] = {
            str(k[0]): cc for k, v in M.group_by(speech, "source_kind").items() if (cc := calibration(v)) is not None}
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


def _err(d: dict) -> dict:
    """Recall-KI → Fehlerrate-KI (1 − Recall, Grenzen getauscht)."""
    return {**d, "value": 1 - d["value"], "lo": 1 - d["hi"], "hi": 1 - d["lo"]}


def to_markdown(s: dict) -> str:
    lines = ["# ASR-Benchmark", "", "Werte in %, [95 %-KI, Szenario-/Sprecher-Bootstrap]. Fachbegriff-Fehler = Anteil der "
             "Fachbegriff-Vorkommen der Referenz, die in der Hypothese fehlen. Zahlen: Uhrzeit/Datum/Menge (Zahl + "
             "Einheit)/sonstige Zahl, Schreibweisen vereinheitlicht (7.30 Uhr = 07:30, 190 Kubik = 190 m³).", ""]
    hdr = ("| Gruppe | n | WER ↓ | CER ↓ | Fachbegriff-Fehler ↓ (n) | Uhrzeit ↑ (n) | Datum ↑ (n) | Menge ↑ (n) "
           "| sonst. Zahl ↑ (n) | Sprach-ID ↑ |")
    sep = "|---|---|---|---|---|---|---|---|---|---|"

    def cell(d, n):
        return f"{M.fmt_ci(d)} ({n})" if n else "–"

    def row(name, d):
        return (f"| {name} | {d['n']} | {M.fmt_ci(d['WER'])} | {M.fmt_ci(d['CER'])} "
                f"| {cell(_err(d['term_recall']), d['n_terms'])} | {cell(d['time_recall'], d['n_time'])} "
                f"| {cell(d['date_recall'], d['n_date'])} | {cell(d['quantity_recall'], d['n_quantity'])} "
                f"| {cell(d['other_number_recall'], d['n_other_number'])} | {M.fmt_ci(d['lang_id_acc'])} |")
    lines += [hdr, sep, row("gesamt", s["overall"])]
    for key in ["by_" + "_x_".join(k) for k in GROUPINGS]:
        if s.get(key):
            lines += ["", f"**{key[3:]}**", "", hdr, sep]
            lines += [row(g, d) for g, d in s[key].items()]
    if "word_score_calibration" in s:
        c = s["word_score_calibration"]
        lines += ["", "## Wort-Score (asr_score) – trennt er richtige von falschen Wörtern?", "",
                  "| Gruppe | AUROC ↑ | ECE ↓ | Wort-Genauigkeit | Wörter |", "|---|---|---|---|---|",
                  f"| gesamt | {c['auroc_correct_vs_wrong']:.3f} | {c['ece']:.3f} | {100 * c['word_acc']:.1f} % "
                  f"| {c['n_words']} |"]
        for key in ("word_score_calibration_by_snr_db", "word_score_calibration_by_source_kind"):
            for g, c in s.get(key, {}).items():
                lines.append(f"| {key.split('_by_')[1]}={g} | {c['auroc_correct_vs_wrong']:.3f} | {c['ece']:.3f} "
                             f"| {100 * c['word_acc']:.1f} % | {c['n_words']} |")
    if s.get("latency"):
        L = s["latency"]
        lines += ["", "## Laufzeit (ohne Warm-up)", "",
                  f"RTF {L['rtf']:.3f} (p95 {L['rtf_p95']:.3f}) · Latenz je Clip p50 {L['latency_p50_s']:.2f} s, "
                  f"p95 {L['latency_p95_s']:.2f} s, max {L['latency_max_s']:.2f} s · Ø Audiodauer "
                  f"{L['audio_s_mean']:.1f} s · Warm-up {L['warmup_s']:.1f} s · n={L['n']}"]
    if "hallucination" in s:
        h = s["hallucination"]
        lines += ["", f"Halluzination auf reinem Lärm/Stille: {h['words_per_min'] or 0:.1f} Wörter/min, "
                      f"{100 * h['clips_with_output']:.0f} % der Clips mit Ausgabe ({h['n_clips']} Clips)"]
    if s.get("most_missed_terms"):
        lines += ["", "Häufigste verfehlte Fachbegriffe: " + ", ".join(f"{t} ({k})" for t, k in s["most_missed_terms"])]
    return "\n".join(lines) + "\n"


def plot_curves(s: dict, out: Path) -> list[str]:
    """WER/Fachbegriff-Fehler/Zahlen-Recall über SNR, je Sprache und je Akzentgruppe (mit 95 %-KI)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    order = lambda g: float("inf") if g == "clean" else float(g)  # noqa: E731
    files = []
    for key, label in (("by_lang_x_snr_db", "Sprache"), ("by_accent_group_x_snr_db", "Akzentgruppe"),
                       ("by_source_kind_x_snr_db", "Quelle")):
        series: dict[str, list] = {}
        for g, d in s.get(key, {}).items():
            name, snr = g.split("|")
            if snr in ("None",):
                continue
            series.setdefault(name, []).append((snr, d))
        if not series:
            continue
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
        for ax, (metric, title, err) in zip(axes, (("WER", "WER ↓", False), ("term_recall", "Fachbegriff-Fehler ↓", True),
                                                   ("number_recall", "Zahlen-Recall ↑", False))):
            for name, pts in sorted(series.items()):
                pts = sorted(pts, key=lambda p: order(p[0]))
                xs = list(range(len(pts)))
                ds = [_err(p[1][metric]) if err else p[1][metric] for p in pts]
                ys = [100 * d["value"] for d in ds]
                lo = [100 * (d["value"] - d["lo"]) if d["lo"] == d["lo"] else 0 for d in ds]
                hi = [100 * (d["hi"] - d["value"]) if d["hi"] == d["hi"] else 0 for d in ds]
                ax.errorbar(xs, ys, yerr=[lo, hi], marker="o", capsize=3, label=f"{name}")
                ax.set_xticks(xs, [f"{p[0]} dB" if p[0] != "clean" else "clean" for p in pts])
            ax.set_title(title)
            ax.set_xlabel("SNR")
            ax.set_ylabel("%")
            ax.grid(alpha=0.3)
        axes[0].legend(title=label, fontsize=8)
        fig.tight_layout()
        f = out / f"curve_{key[3:]}.png"
        fig.savefig(f, dpi=130)
        plt.close(fig)
        files.append(f.name)
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--hyps", type=Path, help="vorhandene Hypothesen (jsonl mit id) statt live transkribieren")
    ap.add_argument("--terms", type=Path, help="Fachbegriffe, eine Zeile je Begriff (Standard: aus models.toml)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=None, help="nur die ersten n Zeilen (Smoke-Test)")
    a = ap.parse_args()
    manifest = load_jsonl(a.manifest)[: a.limit]
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
    s["latency"] = latency(rows) if hyps is None else {}
    s["config"] = {k: settings.models()["asr"].get(k) for k in ("backend", "model", "language", "beam_size")}
    (a.out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = to_markdown(s)
    plots = plot_curves(s, a.out)
    md += "".join(f"\n![{p}]({p})\n" for p in plots)
    (a.out / "summary.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
