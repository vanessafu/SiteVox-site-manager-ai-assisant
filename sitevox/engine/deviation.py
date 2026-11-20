"""Abweichungs-Engine: tägliches Soll-Ist, Alarme, Auswirkung auf Folgetermine.

Alarmregeln (config/rules.toml [alerts]):
  * Tagesleistung < 85 % des Tagessolls
  * Vorgang auf kritischem Pfad >= 1 AT verzögert
  * Prognose überschreitet Vertragstermin (Meilenstein)
Beispiel-Ausgabe: "Bewehrung BP +2 AT → Betonage BP 24.11.–26.11. → Wände EG fertig 18.12. statt 16.12."
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .. import settings, store
from . import schedule


def _de(d: date | str) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return d.strftime("%d.%m.")


def blocks_from_events(evs: list[dict]) -> dict[str, date]:
    out: dict[str, date] = {}
    for e in evs:
        if e.get("blocked_until") and e.get("status") != "dismissed":
            for aid in e.get("activity_ids", []):
                d = date.fromisoformat(e["blocked_until"])
                out[aid] = max(out.get(aid, d), d)
    return out


def daily_target(a: dict, cal: schedule.WorkCalendar, day: date) -> float:
    if a["kind"] == "milestone" or not cal.is_workday(day):
        return 0.0
    s, f = date.fromisoformat(a["start"]), date.fromisoformat(a["finish"])
    return a["qty"] / max(a["duration"], 1) if s <= day <= f else 0.0


def analyze(project_id: str, day: date) -> dict[str, Any]:
    acts = store.activities(project_id)
    if not acts:
        return {"activities": [], "alerts": [], "kpis": {}, "impact": [], "milestones": []}
    prog = store.progress(project_id)
    evs = store.events(project_id)
    rules = settings.rules()
    fc = schedule.forecast(acts, prog, day, blocks_from_events(evs))
    cal: schedule.WorkCalendar = fc["calendar"]
    today_idx = fc["status_idx"]

    rows, alerts = [], []
    ev_by_act: dict[str, list[str]] = {}
    for e in evs:
        if e.get("status") == "dismissed":
            continue
        for aid in e.get("activity_ids", []):
            ev_by_act.setdefault(aid, []).append(e["event_id"])

    total_lv = sum(a["lv_sum"] for a in acts) or 1.0
    ev_ist = ev_soll = 0.0
    day_soll_val = day_ist_val = 0.0
    for a in acts:
        st = schedule.activity_status(a, prog, day)
        f = fc["activities"][a["id"]]
        # Soll-Fortschritt bis heute (linear über die geplanten AT)
        ps, pf = f["planned_start_idx"], f["planned_finish_idx"]
        planned_pct = 0.0 if a["kind"] == "milestone" else \
            min(1.0, max(0.0, (today_idx - ps + 1) / max(pf - ps + 1, 1)))
        ev_ist += a["lv_sum"] * st["pct"]
        ev_soll += a["lv_sum"] * planned_pct
        soll_today = daily_target(a, cal, day)
        ist_today = sum(p["qty"] for p in st["history"] if p["date"] == day.isoformat())
        unit_price = a["lv_sum"] / a["qty"] if a["qty"] else 0
        day_soll_val += soll_today * unit_price
        day_ist_val += ist_today * unit_price
        ratio = (ist_today / soll_today) if soll_today else None
        row = {
            "id": a["id"], "name": a["name"], "kind": a["kind"], "unit": a.get("unit"), "qty": a["qty"],
            "lv_pos": a.get("lv_pos"), "lv_sum": a["lv_sum"],
            "planned_start": a["start"], "planned_finish": a["finish"],
            "planned_start_idx": ps, "planned_finish_idx": pf,
            "forecast_start": f["forecast_start"], "forecast_finish": f["forecast_finish"],
            "forecast_start_idx": f["forecast_start_idx"], "forecast_finish_idx": f["forecast_finish_idx"],
            "delay_days": f["delay_days"], "total_float": f["total_float"], "critical": f["critical"],
            "actual_start": st["actual_start"], "cum": st["cum"], "pct": round(st["pct"], 3),
            "planned_pct": round(planned_pct, 3),
            "today": {"soll": round(soll_today, 2), "ist": round(ist_today, 2),
                      "ratio": round(ratio, 3) if ratio is not None else None},
            "events": ev_by_act.get(a["id"], []),
            "forecast_rate": f.get("rate"), "remaining": f.get("remaining"),
        }
        rows.append(row)
        if ratio is not None and ratio < rules["alerts"]["daily_output_min_ratio"]:
            alerts.append({
                "kind": "daily_output", "activity_id": a["id"], "severity": "warn" if ratio >= 0.6 else "critical",
                "message": f"{a['name']}: Tagesleistung {ratio:.0%} des Tagessolls "
                           f"({ist_today:g} / {soll_today:g} {a.get('unit') or ''})".replace(".", ","),
                "events": ev_by_act.get(a["id"], []),
            })
        if a["kind"] != "milestone" and f["critical"] and f["delay_days"] >= rules["alerts"]["critical_delay_days"]:
            alerts.append({
                "kind": "critical_delay", "activity_id": a["id"], "severity": "critical",
                "message": f"{a['name']} (kritischer Pfad): Verzug {f['delay_days']} AT, "
                           f"Prognose Ende {_de(f['forecast_finish'])} statt {_de(a['finish'])}",
                "events": ev_by_act.get(a["id"], []),
            })

    milestones = []
    for a in acts:
        if a["kind"] != "milestone":
            continue
        f = fc["activities"][a["id"]]
        m = {"id": a["id"], "name": a["name"], "date": a["finish"],
             "at_remaining": f["planned_finish_idx"] - today_idx,
             "forecast": f["forecast_finish"], "overrun_days": max(0, f["delay_days"])}
        milestones.append(m)
        if m["overrun_days"] > 0:
            alerts.append({"kind": "milestone", "activity_id": a["id"], "severity": "critical",
                           "message": f"{a['name']} ({_de(a['finish'])}): Prognose überschreitet um "
                                      f"{m['overrun_days']} AT", "events": []})

    crit_delay = max([r["delay_days"] for r in rows if r["critical"] and r["kind"] != "milestone"] + [0])
    kpis = {
        "progress_ist": round(ev_ist / total_lv, 3),
        "progress_soll": round(ev_soll / total_lv, 3),
        "critical_delay_days": crit_delay,
        "next_deadline": min(milestones, key=lambda m: m["at_remaining"]) if milestones else None,
        "day_target_ratio": round(day_ist_val / day_soll_val, 3) if day_soll_val else None,
    }
    return {
        "date": day.isoformat(), "today_idx": today_idx, "origin": cal.origin.isoformat(),
        "activities": rows, "alerts": alerts, "kpis": kpis, "milestones": milestones,
        "impact": impact_chains(acts, rows),
        "window": window(cal, rows),
    }


def window(cal: schedule.WorkCalendar, rows: list[dict]) -> dict[str, Any]:
    lo = min(r["planned_start_idx"] for r in rows)
    hi = max(max(r["planned_finish_idx"], r["forecast_finish_idx"]) for r in rows)
    weeks = []
    for idx in range(lo, hi + 1):
        d = cal.date_of(idx)
        kw = d.isocalendar().week
        if not weeks or weeks[-1]["kw"] != kw:
            weeks.append({"kw": kw, "start_idx": idx, "start": d.isoformat()})
    return {"start_idx": lo, "end_idx": hi, "weeks": weeks,
            "days": [{"idx": i, "date": cal.date_of(i).isoformat()} for i in range(lo, hi + 1)]}


def impact_chains(acts: list[dict], rows: list[dict]) -> list[dict[str, Any]]:
    """Ursprungsvorgänge mit Verzug → Kette der verschobenen Nachfolger bis zum Vertragstermin."""
    by_id = {r["id"]: r for r in rows}
    delayed = {r["id"] for r in rows if r["delay_days"] > 0}

    def drives(pred: dict, succ_id: str) -> bool:
        # Ein verzögerter Vorgänger treibt den Nachfolger nur über FS – oder über SS, solange dieser nicht begonnen hat
        return pred["id"] in delayed and (pred["type"] == "FS" or not by_id[succ_id]["actual_start"])

    succ: dict[str, list[str]] = {}
    for a in acts:
        for p in a["preds"]:
            if drives(p, a["id"]):
                succ.setdefault(p["id"], []).append(a["id"])
    roots = [r for r in rows if r["id"] in delayed and r["kind"] != "milestone"
             and not any(drives(p, r["id"]) for p in next(a for a in acts if a["id"] == r["id"])["preds"])]
    chains = []
    for root in roots:
        steps, cur, seen = [], root["id"], set()
        while cur and cur not in seen:
            seen.add(cur)
            r = by_id[cur]
            if r["kind"] == "milestone":
                steps.append(f"{r['name']} ({_de(r['planned_finish'])}) um {r['delay_days']} AT überschritten")
            elif cur == root["id"]:
                steps.append(f"{r['name']} +{r['delay_days']} AT")
            else:
                steps.append(f"{r['name']} {_de(r['forecast_start'])}–{_de(r['forecast_finish'])} "
                             f"(statt {_de(r['planned_start'])}–{_de(r['planned_finish'])})")
            nxt = [s for s in succ.get(cur, []) if s in delayed]
            nxt.sort(key=lambda s: (not by_id[s]["critical"], by_id[s]["forecast_start_idx"]))
            cur = nxt[0] if nxt else None
        chains.append({"root": root["id"], "critical": root["critical"], "delay_days": root["delay_days"],
                       "events": root["events"], "text": " → ".join(steps), "steps": steps})
    chains.sort(key=lambda c: (not c["critical"], -c["delay_days"]))
    return chains
