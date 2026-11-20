"""Feld-Konfidenz OHNE LLM-Selbstauskunft.

Signale (gewichtet, auf vorhandene Signale renormiert, Gewichte in rules.toml [confidence]):
  evidence     – Feld zeigt auf >= 1 Rohbeleg? (kein Beleg → 0, sofort rot)
  asr          – mittlerer Wort-Score der zugehörigen Audiostelle
  consistency  – Übereinstimmung über n Stichproben (temperature > 0)
  retrieval    – Rerank-/Abdeckungs-Score der zitierten Vertrags-/LV-Stelle
  rule         – deterministische Plausibilitätsregel (Verstoß → Abzug)
Ampel: >= 0.8 grün, 0.5–0.8 gelb, < 0.5 rot (manuelle Bestätigung nötig).
Review-Queue: Priorität = (1 − Konfidenz) × Feldwichtigkeit.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Optional

from . import settings


def _cfg() -> dict:
    return settings.rules()["confidence"]


def band(v: float) -> str:
    c = _cfg()
    return "green" if v >= c["green_min"] else "yellow" if v >= c["yellow_min"] else "red"


def evidence_signal(n: int) -> float:
    return 0.0 if n <= 0 else min(1.0, 0.7 + 0.15 * (n - 1))


def agreement(values: Iterable[Any]) -> tuple[Any, float]:
    """Modalwert und Anteil der Stichproben, die ihn liefern. Listen werden als Mengen verglichen."""
    vals = [tuple(sorted(v)) if isinstance(v, list) else v for v in values]
    if not vals:
        return None, 0.0
    cnt = Counter(vals)
    val, k = cnt.most_common(1)[0]
    if isinstance(val, tuple):
        val = list(val)
    return val, k / len(vals)


def combine(*, n_evidence: int, asr: Optional[float] = None, consistency: Optional[float] = None,
            retrieval: Optional[float] = None, rule_ok: Optional[bool] = None) -> dict[str, Any]:
    c = _cfg()
    signals: dict[str, float] = {"evidence": evidence_signal(n_evidence)}
    if n_evidence <= 0:
        return {"value": 0.0, "band": "red", "signals": signals, "reason": "kein Beleg"}
    weights = {"evidence": c["w_evidence"]}
    if asr is not None:
        signals["asr"], weights["asr"] = asr, c["w_asr"]
    if consistency is not None:
        signals["consistency"], weights["consistency"] = consistency, c["w_consistency"]
    if retrieval is not None:
        signals["retrieval"], weights["retrieval"] = retrieval, c["w_retrieval"]
    if rule_ok is not None:
        signals["rule"], weights["rule"] = (1.0 if rule_ok else 0.0), c["w_rule"]
    v = sum(signals[k] * weights[k] for k in weights) / sum(weights.values())
    if rule_ok is False:
        v *= 1 - c["rule_violation_penalty"]
    v = round(max(0.0, min(1.0, v)), 3)
    return {"value": v, "band": band(v), "signals": {k: round(s, 3) for k, s in signals.items()}}


def importance(field: str) -> float:
    imp = _cfg()["importance"]
    return float(imp.get(field, imp["default"]))


def priority(conf: float, field: str) -> float:
    return round((1 - conf) * importance(field), 4)
