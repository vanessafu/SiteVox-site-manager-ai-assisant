"""Tagesverlauf 07–17 Uhr je Gerät/Kolonne: Arbeit / eingeschränkt / Stillstand / geplant-nicht-begonnen.

Basis: Einsatzplan aus baseline.yaml (resources). Überlagert durch Tagesbuch-Einträge (equipment_use) und
resource_effects der Ereignisse; Geräte, die nur gemeldet wurden, erscheinen als ungeplante Zeile.
Priorität: idle > planned_not_started > restricted > work.
"""
from __future__ import annotations

from typing import Any

from .. import settings, store

PRIO = {"none": 0, "work": 1, "restricted": 2, "planned_not_started": 3, "idle": 4}


def _m(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _match(resource_cfg: dict, name: str) -> bool:
    n = name.lower()
    return resource_cfg["name"].lower() in n or n in resource_cfg["name"].lower() or resource_cfg["id"] in n


# Tagesbuch-Zustand → Tagesverlauf-Status (checked_ok = Altdaten: ändert den Verlauf nicht, nur Bemerkung)
LOG_STATUS = {"in_operation": "work", "restricted": "restricted", "idle": "idle", "not_used": "planned_not_started",
              "under_inspection": "restricted", "checked_ok": None}


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def day_timeline(project_id: str, day: str, planned_activity_ids: set[str]) -> dict[str, Any]:
    """Zeilen = Einsatzplan (baseline resources) + Geräte, die nur in Meldungen/Ereignissen vorkommen
    (unplanned=True, z. B. ein zusätzlich angemieteter Radlader). Überlagerung: Plan → Tagesbuch → Ereignisse."""
    cal = settings.rules()["calendar"]
    t0, t1 = _m(cal["shift_start"]), _m(cal["shift_end"])
    pcfg = settings.project_cfg(project_id)
    evs = [e for e in store.events(project_id, day) if e.get("status") != "dismissed"]
    logs = [l for l in store.log_entries(project_id, day, "equipment_use") if l.get("resource")]
    specs = [dict(r, unplanned=False) for r in pcfg.get("resources", [])]

    def find(name: str) -> dict | None:
        return next((r for r in specs if (not r["unplanned"] and _match(r, name)) or _norm(r["name"]) == _norm(name)),
                    None)

    for name in [l["resource"] for l in logs] + [eff["resource"] for e in evs for eff in e.get("resource_effects", [])]:
        if name and not find(name):
            specs.append({"id": f"adhoc:{_norm(name)}", "name": name.strip(), "activity": None, "unplanned": True})

    rows = []
    for r in specs:
        slots = ["none"] * (t1 - t0)
        src: list[str | None] = [None] * (t1 - t0)
        planned = not r["unplanned"] and r.get("activity") in planned_activity_ids
        if planned:
            for i in range(max(_m(r["from"]), t0) - t0, min(_m(r["to"]), t1) - t0):
                slots[i] = "work"
        mine = [l for l in logs if find(l["resource"]) is r]
        for l in mine:
            st = LOG_STATUS.get(l.get("state") or "")
            if not st:
                continue
            if l.get("start_time"):
                a_, b_ = _m(l["start_time"]), _m(l["end_time"]) if l.get("end_time") else t1
            elif planned:
                a_, b_ = _m(r["from"]), _m(r["to"])
            else:
                continue  # ungeplant und ohne Uhrzeit: Status ja, Zeitbalken nein (nichts erfinden)
            for i in range(max(a_, t0) - t0, min(b_, t1) - t0):
                if PRIO[st] >= PRIO[slots[i]]:
                    slots[i] = st
        for e in evs:
            for eff in e.get("resource_effects", []):
                if find(eff["resource"]) is not r:
                    continue
                end = _m(eff["end"]) if eff.get("end") else (_m(r["to"]) if r.get("to") else t1)
                a = max(_m(eff["start"]), t0) - t0
                b = min(end, t1) - t0
                for i in range(a, b):
                    if PRIO[eff["status"]] >= PRIO[slots[i]]:
                        slots[i] = eff["status"]
                        src[i] = e["event_id"]
        segs = []
        for i, s_ in enumerate(slots):
            if s_ == "none":
                continue
            if segs and segs[-1]["status"] == s_ and segs[-1]["_end"] == i and segs[-1]["event_id"] == src[i]:
                segs[-1]["_end"] = i + 1
            else:
                segs.append({"status": s_, "_start": i, "_end": i + 1, "event_id": src[i]})
        for s_ in segs:
            s_["start"], s_["end"] = _hhmm(t0 + s_.pop("_start")), _hhmm(t0 + s_.pop("_end"))
            s_["from_pct"] = round((_m(s_["start"]) - t0) / (t1 - t0), 4)
            s_["to_pct"] = round((_m(s_["end"]) - t0) / (t1 - t0), 4)
        rows.append({"id": r["id"], "name": r["name"], "activity_id": r.get("activity"), "segments": segs,
                     "unplanned": r["unplanned"], "log_ids": [l["log_id"] for l in mine],
                     "log_state": mine[-1].get("state") if mine else None,
                     "remarks": [l.get("text") or l.get("quote") for l in mine],
                     "log_evidence": [l["evidence_id"] for l in mine if l.get("evidence_id")]})
    markers = []
    for c in store.captures(project_id, day):
        hhmm = c["captured_at"][11:16]
        pos = (_m(hhmm) - t0) / (t1 - t0)
        markers.append({"capture_id": c["capture_id"], "kind": c["kind"], "time": hhmm,
                        "pos": round(min(max(pos, 0), 1), 4), "title": c.get("title", ""),
                        "events": c.get("event_ids", [])})
    return {"start": cal["shift_start"], "end": cal["shift_end"], "rows": rows, "markers": markers}
