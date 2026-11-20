"""Tagesverlauf 07–17 Uhr je Gerät/Kolonne: Arbeit / eingeschränkt / Stillstand / geplant-nicht-begonnen.

Basis: Einsatzplan aus baseline.yaml (resources). Überlagert durch resource_effects der Ereignisse.
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


def day_timeline(project_id: str, day: str, planned_activity_ids: set[str]) -> dict[str, Any]:
    cal = settings.rules()["calendar"]
    t0, t1 = _m(cal["shift_start"]), _m(cal["shift_end"])
    pcfg = settings.project_cfg(project_id)
    evs = [e for e in store.events(project_id, day) if e.get("status") != "dismissed"]
    rows = []
    for r in pcfg.get("resources", []):
        slots = ["none"] * (t1 - t0)
        src: list[str | None] = [None] * (t1 - t0)
        if r.get("activity") in planned_activity_ids:
            for i in range(max(_m(r["from"]), t0) - t0, min(_m(r["to"]), t1) - t0):
                slots[i] = "work"
        for e in evs:
            for eff in e.get("resource_effects", []):
                if not _match(r, eff["resource"]):
                    continue
                a = max(_m(eff["start"]), t0) - t0
                b = (min(_m(eff["end"]), t1) if eff.get("end") else min(_m(r["to"]), t1)) - t0
                for i in range(a, b):
                    if PRIO[eff["status"]] >= PRIO[slots[i]]:
                        slots[i] = eff["status"]
                        src[i] = e["event_id"]
        segs = []
        for i, s in enumerate(slots):
            if s == "none":
                continue
            if segs and segs[-1]["status"] == s and segs[-1]["_end"] == i and segs[-1]["event_id"] == src[i]:
                segs[-1]["_end"] = i + 1
            else:
                segs.append({"status": s, "_start": i, "_end": i + 1, "event_id": src[i]})
        for s in segs:
            s["start"], s["end"] = _hhmm(t0 + s.pop("_start")), _hhmm(t0 + s.pop("_end"))
            s["from_pct"] = round((_m(s["start"]) - t0) / (t1 - t0), 4)
            s["to_pct"] = round((_m(s["end"]) - t0) / (t1 - t0), 4)
        rows.append({"id": r["id"], "name": r["name"], "activity_id": r.get("activity"), "segments": segs})
    markers = []
    for c in store.captures(project_id, day):
        hhmm = c["captured_at"][11:16]
        pos = (_m(hhmm) - t0) / (t1 - t0)
        markers.append({"capture_id": c["capture_id"], "kind": c["kind"], "time": hhmm,
                        "pos": round(min(max(pos, 0), 1), 4), "title": c.get("title", ""),
                        "events": c.get("event_ids", [])})
    return {"start": cal["shift_start"], "end": cal["shift_end"], "rows": rows, "markers": markers}
