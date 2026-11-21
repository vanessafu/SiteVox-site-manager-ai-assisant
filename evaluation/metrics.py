"""Metriken für kleine, eigene Testsets: WER/CER, Fachbegriff-/Zahlen-Recall, P/R/F1,
Cluster-Bootstrap-Konfidenzintervalle, McNemar, Kalibrierung (ECE, Risk-Coverage).

Grundregel bei wenig Daten: immer nach *Szenario* clustern (Varianten eines Szenarios – Sprache,
Sprecher, SNR – sind korreliert) und Intervalle statt Punktwerte berichten.
"""
from __future__ import annotations

import math
import random
import re
import unicodedata
from collections import defaultdict
from typing import Any, Callable, Iterable, Optional, Sequence

# ----------------------------------------------------------------------------- Text-Normalisierung
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(s: str) -> str:
    """Kleinschreibung, Satzzeichen weg (Umlaute, ş/ğ/ı, ą/ł/ż bleiben), Dezimalkomma → Punkt."""
    # Türkisch: "İ".lower() = "i" + U+0307 (kombinierender Punkt) → würde das Wort zerreißen
    s = unicodedata.normalize("NFC", (s or "").replace("İ", "i")).lower().replace("\u0307", "")
    s = re.sub(r"(\d),(\d)", r"\1.\2", s)
    s = re.sub(r"(?<=\d)\.(?=\d)", "qqdotqq", s)          # Dezimalpunkt/Datum vor Satzzeichen-Entfernung schützen
    s = re.sub(r"(?<=\d):(?=\d{2}\b)", "qqcolonqq", s)    # Uhrzeit schützen
    s = _PUNCT.sub(" ", s).replace("qqcolonqq", ":").replace("qqdotqq", ".")
    return " ".join(s.split())


def tokens(s: str) -> list[str]:
    return normalize(s).split()


# ----------------------------------------------------------------------------- Edit-Distanz
def align(ref: Sequence[str], hyp: Sequence[str]) -> list[tuple[str, Optional[str], Optional[str]]]:
    """Levenshtein-Alignment → [(op, ref_tok, hyp_tok)], op ∈ {ok, sub, del, ins}."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            c = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i][j] = min(d[i - 1][j - 1] + c, d[i - 1][j] + 1, d[i][j - 1] + 1)
    ops, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (0 if ref[i - 1] == hyp[j - 1] else 1):
            ops.append(("ok" if ref[i - 1] == hyp[j - 1] else "sub", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            ops.append(("del", ref[i - 1], None))
            i -= 1
        else:
            ops.append(("ins", None, hyp[j - 1]))
            j -= 1
    return ops[::-1]


def edit_counts(ref: Sequence[str], hyp: Sequence[str]) -> dict[str, int]:
    c = {"ok": 0, "sub": 0, "del": 0, "ins": 0}
    for op, _, _ in align(ref, hyp):
        c[op] += 1
    c["errors"] = c["sub"] + c["del"] + c["ins"]
    c["n_ref"] = len(ref)
    return c


def wer_counts(ref: str, hyp: str) -> dict[str, int]:
    return edit_counts(tokens(ref), tokens(hyp))


def cer_counts(ref: str, hyp: str) -> dict[str, int]:
    return edit_counts(list(normalize(ref).replace(" ", "")), list(normalize(hyp).replace(" ", "")))


def hyp_word_correctness(ref: str, hyp_words: list[dict]) -> list[tuple[float, bool]]:
    """(ASR-Wort-Score, korrekt?) je Hypothesenwort – für die Kalibrierung von asr_score."""
    hw = [(normalize(w.get("word", "")), w.get("score")) for w in hyp_words]
    hw = [(t, s) for t, s in hw if t]
    flat: list[tuple[str, Optional[float]]] = []
    for t, s in hw:                                  # normalize kann ein Wort in mehrere Tokens teilen
        flat += [(x, s) for x in t.split()]
    ops = align(tokens(ref), [t for t, _ in flat])
    out, j = [], 0
    for op, _, _ in ops:
        if op == "del":
            continue
        s = flat[j][1]
        if s is not None:
            out.append((float(s), op == "ok"))
        j += 1
    return out


# ----------------------------------------------------------------------------- Fach-Entitäten
def term_hits(ref: str, hyp: str, terms: Iterable[str]) -> tuple[int, int, list[str]]:
    """Wie viele Vorkommen der Fachbegriffe aus der Referenz stehen auch in der Hypothese?"""
    r, h = f" {normalize(ref)} ", f" {normalize(hyp)} "
    hit = total = 0
    missed = []
    for t in terms:
        nt = normalize(t)
        if not nt:
            continue
        k = r.count(f" {nt} ")
        if k:
            got = min(k, h.count(f" {nt} "))
            hit, total = hit + got, total + k
            if got < k:
                missed.append(t)
    return hit, total, missed


_NUM = re.compile(r"\d+(?:[.:]\d+)?")


def number_hits(ref: str, hyp: str) -> tuple[int, int]:
    """Multiset-Überdeckung aller Zahlen/Uhrzeiten (14, 190, 07:30, 4.5) – Fehler hier landen in Schreiben/Fristen."""
    def nums(s):
        out = defaultdict(int)
        for x in _NUM.findall(normalize(s)):
            if ":" in x:
                h, m = x.split(":")
                x = f"{int(h)}:{m}"
            else:
                x = f"{float(x):g}"
            out[x] += 1
        return out
    rn, hn = nums(ref), nums(hyp)
    return sum(min(k, hn.get(v, 0)) for v, k in rn.items()), sum(rn.values())


# ----------------------------------------------------------------------------- Klassifikation
def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * p * r / (p + r) if tp and p + r else (0.0 if tp + fp + fn else float("nan"))
    return {"precision": p, "recall": r, "f1": f, "tp": tp, "fp": fp, "fn": fn}


def macro_f1(pairs: list[tuple[str, str]]) -> float:
    """pairs = [(gold, pred)] → Macro-F1 über alle Gold-Klassen."""
    labels = sorted({g for g, _ in pairs})
    fs = []
    for lab in labels:
        tp = sum(g == lab and p == lab for g, p in pairs)
        fp = sum(g != lab and p == lab for g, p in pairs)
        fn = sum(g == lab and p != lab for g, p in pairs)
        fs.append(prf(tp, fp, fn)["f1"])
    return sum(fs) / len(fs) if fs else float("nan")


def confusion(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    m: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for g, p in pairs:
        m[g][p] += 1
    return {g: dict(v) for g, v in m.items()}


# ----------------------------------------------------------------------------- Statistik
def cluster_bootstrap(items: list[dict], stat: Callable[[list[dict]], float], cluster: str = "scenario_id",
                      n: int = 2000, seed: int = 0, alpha: float = 0.05) -> dict[str, float]:
    """Punktwert + (1-alpha)-Perzentil-KI; es werden ganze Cluster (Szenarien) gezogen."""
    groups: dict[Any, list[dict]] = defaultdict(list)
    for it in items:
        groups[it.get(cluster, it.get("id"))].append(it)
    keys = list(groups)
    point = stat(items)
    if len(keys) < 2:
        return {"value": point, "lo": float("nan"), "hi": float("nan"), "n_clusters": len(keys), "n": len(items)}
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        sample = [x for k in rng.choices(keys, k=len(keys)) for x in groups[k]]
        v = stat(sample)
        if not math.isnan(v):
            vals.append(v)
    vals.sort()
    lo = vals[int(alpha / 2 * len(vals))] if vals else float("nan")
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))] if vals else float("nan")
    return {"value": point, "lo": lo, "hi": hi, "n_clusters": len(keys), "n": len(items)}


def ratio(num_key: str, den_key: str) -> Callable[[list[dict]], float]:
    """Mikro-Mittel Σnum/Σden (z. B. WER = Σerrors/Σn_ref) – richtig für Raten über ungleich lange Items."""
    def f(items):
        den = sum(i.get(den_key, 0) for i in items)
        return sum(i.get(num_key, 0) for i in items) / den if den else float("nan")
    return f


def mean_of(key: str) -> Callable[[list[dict]], float]:
    def f(items):
        v = [float(i[key]) for i in items if i.get(key) is not None]
        return sum(v) / len(v) if v else float("nan")
    return f


def mcnemar(a_correct: Sequence[bool], b_correct: Sequence[bool]) -> dict[str, float]:
    """Exakter McNemar-Test für gepaarte Systeme A/B auf denselben Items."""
    b = sum(x and not y for x, y in zip(a_correct, b_correct))
    c = sum(y and not x for x, y in zip(a_correct, b_correct))
    k, nn = min(b, c), b + c
    p = min(1.0, 2 * sum(math.comb(nn, i) for i in range(k + 1)) / 2 ** nn) if nn else 1.0
    return {"a_only": b, "b_only": c, "p": p}


# ----------------------------------------------------------------------------- Kalibrierung
def ece(conf: Sequence[float], correct: Sequence[bool], bins: int = 10) -> float:
    if not conf:
        return float("nan")
    tot, n = 0.0, len(conf)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(conf) if (lo <= c < hi) or (b == bins - 1 and c == 1.0)]
        if idx:
            acc = sum(correct[i] for i in idx) / len(idx)
            avg = sum(conf[i] for i in idx) / len(idx)
            tot += len(idx) / n * abs(acc - avg)
    return tot


def risk_coverage(conf: Sequence[float], correct: Sequence[bool]) -> dict[str, Any]:
    """Nach Konfidenz absteigend automatisch freigeben: Fehlerrate bei jeder Abdeckung + AURC (kleiner = besser)."""
    order = sorted(range(len(conf)), key=lambda i: -conf[i])
    pts, err = [], 0
    for k, i in enumerate(order, 1):
        err += not correct[i]
        pts.append({"coverage": k / len(order), "risk": err / k, "threshold": conf[i]})
    aurc = sum(p["risk"] for p in pts) / len(pts) if pts else float("nan")
    return {"aurc": aurc, "curve": pts}


def auroc(scores: Sequence[float], positive: Sequence[bool]) -> float:
    """P(score(pos) > score(neg)); hier: Score eines korrekten Worts > Score eines falschen Worts."""
    pos = [s for s, y in zip(scores, positive) if y]
    neg = [s for s, y in zip(scores, positive) if not y]
    if not pos or not neg:
        return float("nan")
    ranked = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg])
    rank_sum, i = 0.0, 0
    while i < len(ranked):                               # Rang-Mittel bei Gleichstand
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        r = (i + j + 1) / 2
        rank_sum += r * sum(ranked[k][1] for k in range(i, j))
        i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


# ----------------------------------------------------------------------------- Ausgabe
def fmt_ci(d: dict[str, float], pct: bool = True) -> str:
    f = (lambda x: f"{100 * x:.1f}") if pct else (lambda x: f"{x:.3f}")
    if math.isnan(d["value"]):
        return "—"
    if math.isnan(d.get("lo", float("nan"))):
        return f"{f(d['value'])}"
    return f"{f(d['value'])} [{f(d['lo'])}, {f(d['hi'])}]"


def group_by(items: list[dict], *keys: str) -> dict[tuple, list[dict]]:
    g: dict[tuple, list[dict]] = defaultdict(list)
    for it in items:
        g[tuple(it.get(k) for k in keys)].append(it)
    return dict(sorted(g.items(), key=lambda kv: tuple(str(x) for x in kv[0])))
