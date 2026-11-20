"""Bauzeitenplan: Import (Excel/CSV), Arbeitstagekalender, CPM (Vorwärts/Rückwärts), Prognose.

Reine Python-Logik, deterministisch und reproduzierbar.
Vorgänger-Notation in der Excel-Spalte "Vorgänger": "A40FS-1; A30SS+4" (FS/SS, Lag in Arbeitstagen).
"""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

from .. import settings

PRED_RE = re.compile(r"^\s*([A-Za-z0-9_]+?)(FS|SS)?([+-]\d+)?\s*$")


# ----------------------------------------------------------------------------- calendar
class WorkCalendar:
    def __init__(self, origin: date, workdays: Iterable[int] | None = None, holidays: Iterable[str] | None = None):
        r = settings.rules()["calendar"]
        self.workdays = set(workdays or r["workdays"])
        self.holidays = {date.fromisoformat(h) for h in (holidays or r["holidays"])}
        self.origin = self.next_workday(origin, include=True)

    def is_workday(self, d: date) -> bool:
        return d.isoweekday() in self.workdays and d not in self.holidays

    def next_workday(self, d: date, include: bool = False) -> date:
        if not include:
            d += timedelta(days=1)
        while not self.is_workday(d):
            d += timedelta(days=1)
        return d

    def index(self, d: date) -> int:
        """1-basierter Arbeitstag-Index ab origin (für Nicht-Arbeitstage: der vorherige AT)."""
        if d < self.origin:
            n, cur = 0, self.origin
            while cur > d:
                cur -= timedelta(days=1)
                if self.is_workday(cur):
                    n -= 1
            return n + 1
        n, cur = 0, self.origin
        while cur <= d:
            if self.is_workday(cur):
                n += 1
            cur += timedelta(days=1)
        return n

    def date_of(self, idx: int) -> date:
        cur, n = self.origin, 1
        if idx >= 1:
            while n < idx:
                cur = self.next_workday(cur)
                n += 1
            return cur
        while n > idx:
            cur -= timedelta(days=1)
            while not self.is_workday(cur):
                cur -= timedelta(days=1)
            n -= 1
        return cur

    def between(self, a: date, b: date) -> int:
        """Arbeitstage von a nach b (b - a in AT, kann negativ sein)."""
        return self.index(b) - self.index(a)


# ----------------------------------------------------------------------------- import
def parse_preds(s: str | None) -> list[dict]:
    out = []
    for tok in re.split(r"[;,]", s or ""):
        if not tok.strip():
            continue
        m = PRED_RE.match(tok)
        if not m:
            raise ValueError(f"Vorgänger nicht lesbar: {tok!r}")
        out.append({"id": m.group(1), "type": m.group(2) or "FS", "lag": int(m.group(3) or 0)})
    return out


COLS = {
    "id": ["id", "nr", "vorgangsnummer"],
    "name": ["vorgang", "name", "bezeichnung"],
    "start": ["anfang", "start", "beginn"],
    "finish": ["ende", "finish", "fertig"],
    "qty": ["menge"],
    "unit": ["einheit"],
    "lv_pos": ["lv-pos", "lv_pos", "lvpos"],
    "lv_sum": ["lv-summe", "lv_summe", "betrag"],
    "preds": ["vorgänger", "vorgaenger", "predecessors"],
    "aliases": ["aliase", "aliases", "synonyme"],
    "kind": ["typ", "art"],
}


def _norm_row(row: dict[str, Any]) -> dict[str, Any]:
    low = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
    out: dict[str, Any] = {}
    for key, names in COLS.items():
        for n in names:
            if n in low and low[n] not in (None, ""):
                out[key] = low[n]
                break
    for k in ("start", "finish"):
        v = out.get(k)
        if hasattr(v, "date"):
            out[k] = v.date().isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        elif isinstance(v, str) and re.match(r"\d{2}\.\d{2}\.\d{4}", v):
            d, m, y = v.split(".")
            out[k] = f"{y}-{m}-{d}"
    out["qty"] = float(str(out.get("qty", 0)).replace(",", ".")) if out.get("qty") not in (None, "") else 0.0
    out["lv_sum"] = float(str(out.get("lv_sum", 0)).replace(".", "").replace(",", ".")) \
        if isinstance(out.get("lv_sum"), str) else float(out.get("lv_sum") or 0)
    out["preds"] = parse_preds(out.get("preds"))
    out["aliases"] = [a.strip() for a in str(out.get("aliases") or "").split(";") if a.strip()]
    out["kind"] = "milestone" if str(out.get("kind", "")).lower().startswith(("meil", "mile")) else "task"
    out["id"] = str(out["id"]).strip()
    return out


def import_plan(path: Path) -> list[dict]:
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        ws = load_workbook(path, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        header = [str(h) if h is not None else "" for h in rows[0]]
        raw = [dict(zip(header, r)) for r in rows[1:] if any(c is not None for c in r)]
    else:
        with open(path, encoding="utf-8") as f:
            raw = list(csv.DictReader(f, delimiter=";"))
    acts = [_norm_row(r) for r in raw]
    origin = min(date.fromisoformat(a["start"]) for a in acts if a.get("start"))
    cal = WorkCalendar(origin)
    for a in acts:
        s = date.fromisoformat(a.get("start") or a["finish"])
        f = date.fromisoformat(a.get("finish") or a["start"])
        a["duration"] = 0 if a["kind"] == "milestone" else cal.between(s, f) + 1
    return acts


# ----------------------------------------------------------------------------- CPM
@dataclass
class Node:
    id: str
    name: str
    duration: int
    es: int = 0
    ef: int = 0
    ls: int = 0
    lf: int = 0
    preds: list[dict] = field(default_factory=list)
    succs: list[tuple[str, str, int]] = field(default_factory=list)
    fixed_finish: Optional[int] = None  # Vertragstermin (Meilenstein)
    lf_finish: int = 0

    @property
    def total_float(self) -> int:
        return self.ls - self.es

    @property
    def finish_float(self) -> int:
        """Puffer des Endtermins – maßgeblich dafür, ob ein Verzug Folgetermine verschiebt."""
        return self.lf_finish - self.ef


def _topo(nodes: dict[str, Node]) -> list[str]:
    order, seen = [], set()

    def visit(n: str, stack=()):
        if n in seen:
            return
        if n in stack:
            raise ValueError(f"Zyklus im Terminplan bei {n}")
        for p in nodes[n].preds:
            visit(p["id"], stack + (n,))
        seen.add(n)
        order.append(n)

    for n in nodes:
        visit(n)
    return order


def cpm(acts: list[dict], cal: WorkCalendar, fixed_es: dict[str, int] | None = None,
        durations: dict[str, int] | None = None, min_es: dict[str, int] | None = None) -> dict[str, Node]:
    """Vorwärts-/Rückwärtsrechnung auf AT-Indizes (inklusive Tage: EF = ES + D - 1).

    fixed_es  – bereits begonnene Vorgänge (Ist-Beginn)
    durations – überschriebene Dauern (Prognose)
    min_es    – frühester Beginn (z. B. geplanter Beginn: wir fangen nicht früher an als geplant)
    """
    nodes: dict[str, Node] = {}
    for a in acts:
        d = (durations or {}).get(a["id"], a["duration"])
        n = Node(a["id"], a["name"], d, preds=a["preds"])
        if a["kind"] == "milestone":
            n.fixed_finish = cal.index(date.fromisoformat(a["finish"]))
        nodes[a["id"]] = n
    for n in nodes.values():
        for p in n.preds:
            nodes[p["id"]].succs.append((n.id, p["type"], p["lag"]))
    order = _topo(nodes)
    for nid in order:
        n = nodes[nid]
        es = (min_es or {}).get(nid, 1)
        for p in n.preds:
            pn = nodes[p["id"]]
            if p["type"] == "SS":
                es = max(es, pn.es + p["lag"])
            else:
                es = max(es, pn.ef + 1 + p["lag"])
        if fixed_es and nid in fixed_es:
            es = fixed_es[nid]
        n.es = es
        n.ef = es + max(n.duration, 1) - 1 if n.duration else es - 1
    project_end = max(n.ef for n in nodes.values())
    for nid in reversed(order):
        n = nodes[nid]
        # FS-Nachfolger/Termine begrenzen das Ende, SS-Nachfolger nur den Beginn
        has_fs_succ = any(typ != "SS" for _, typ, _ in n.succs)
        lf = n.fixed_finish if n.fixed_finish is not None else (10 ** 9 if has_fs_succ else project_end)
        ls_cap = 10 ** 9
        for sid, typ, lag in n.succs:
            s = nodes[sid]
            if typ == "SS":
                ls_cap = min(ls_cap, s.ls - lag)
            else:
                lf = min(lf, s.ls - 1 - lag)
        n.lf_finish = lf
        n.ls = min(lf - n.duration + 1 if n.duration else lf + 1, ls_cap)
        n.lf = n.ls + n.duration - 1 if n.duration else n.ls - 1
    return nodes


# ----------------------------------------------------------------------------- status / forecast
def activity_status(a: dict, prog: list[dict], status_date: date) -> dict[str, Any]:
    rows = [p for p in prog if p["activity_id"] == a["id"] and date.fromisoformat(p["date"]) <= status_date
            and p["qty"] > 0]  # "Betonage 0 m³" bedeutet: nicht begonnen
    cum = sum(p["qty"] for p in rows)
    qty = a["qty"] or 1.0
    done = cum >= qty * 0.999 and a["kind"] != "milestone"
    return {
        "cum": round(cum, 2),
        "pct": min(1.0, cum / qty) if a["kind"] != "milestone" else 0.0,
        "actual_start": rows[0]["date"] if rows else None,
        "actual_finish": rows[-1]["date"] if done else None,
        "done": done,
        "history": rows,
    }


def forecast(acts: list[dict], prog: list[dict], status_date: date, blocks: dict[str, date] | None = None,
             window: int | None = None) -> dict[str, Any]:
    """Prognose "bei aktuellem Tempo": Ist-Beginn fix, Restmenge / Ø-Leistung der letzten n AT,
    Blockaden (z. B. fehlende Pläne bis Montag) verschieben die Wiederaufnahme.
    """
    window = window or settings.rules()["alerts"]["forecast_window_days"]
    origin = min(date.fromisoformat(a["start"]) for a in acts)
    cal = WorkCalendar(origin)
    status_idx = cal.index(status_date)
    planned_starts = {a["id"]: cal.index(date.fromisoformat(a["start"])) for a in acts if a["kind"] != "milestone"}
    base = cpm(acts, cal, min_es=planned_starts)
    fixed_es, durations, min_es, info = {}, {}, {}, {}
    for a in acts:
        st = activity_status(a, prog, status_date)
        planned_s = cal.index(date.fromisoformat(a["start"]))
        min_es[a["id"]] = planned_s
        if a["kind"] == "milestone":
            continue
        if st["actual_start"]:
            s_idx = cal.index(date.fromisoformat(st["actual_start"]))
            fixed_es[a["id"]] = s_idx
            if st["done"]:
                durations[a["id"]] = cal.index(date.fromisoformat(st["actual_finish"])) - s_idx + 1
            else:
                recent = [r["qty"] for r in st["history"]][-window:]
                rate = (sum(recent) / len(recent)) if recent and sum(recent) > 0 else a["qty"] / max(a["duration"], 1)
                remaining = max(0.0, a["qty"] - st["cum"])
                rem_days = math.ceil(remaining / rate - 1e-9) if remaining > 0 else 0
                resume = status_idx + 1
                if blocks and a["id"] in blocks:
                    resume = max(resume, cal.index(blocks[a["id"]]) + 1)
                finish = resume + rem_days - 1 if rem_days else status_idx
                durations[a["id"]] = finish - s_idx + 1
                info[a["id"]] = {"rate": round(rate, 2), "remaining": round(remaining, 2), "resume_idx": resume}
        elif blocks and a["id"] in blocks:
            min_es[a["id"]] = max(planned_s, cal.index(blocks[a["id"]]) + 1)
    fc = cpm(acts, cal, fixed_es=fixed_es, durations=durations, min_es=min_es)
    out = {}
    for a in acts:
        b, f = base[a["id"]], fc[a["id"]]
        planned_f = cal.index(date.fromisoformat(a["finish"]))
        fin = f.ef if a["kind"] != "milestone" else max(fc[p["id"]].ef for p in a["preds"]) if a["preds"] else f.ef
        out[a["id"]] = {
            "planned_start_idx": cal.index(date.fromisoformat(a["start"])),
            "planned_finish_idx": planned_f,
            "forecast_start_idx": f.es,
            "forecast_finish_idx": fin,
            "forecast_start": cal.date_of(f.es).isoformat(),
            "forecast_finish": cal.date_of(fin).isoformat(),
            "delay_days": fin - planned_f,
            "total_float": b.finish_float,
            "critical": b.finish_float <= 0,
            **info.get(a["id"], {}),
        }
    return {"calendar": cal, "status_idx": status_idx, "activities": out}
