"""Wetter (DWD-Daten über Bright Sky): füllt die Wetterspalte im Bautagebuch und prüft, ob die Witterung
über das bei Angebotsabgabe zu erwartende Maß hinausgeht (§ 6 Abs. 2 Nr. 2 VOB/B).
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any, Optional

import httpx

from .. import settings


def fetch(lat: float, lon: float, day: date, project_id: Optional[str] = None) -> dict[str, Any]:
    if settings.is_demo():
        fx = settings.demo_dir(project_id or "BV-RIEM") / "fixtures" / "weather" / f"{day.isoformat()}.json"
        if fx.exists():
            return json.loads(fx.read_text(encoding="utf-8"))
    if os.environ.get("SITEVOX_WEATHER_ONLINE", "1") == "0":
        raise RuntimeError("Wetterabruf online abgeschaltet (SITEVOX_WEATHER_ONLINE=0)")
    r = settings.rules()["weather"]
    resp = httpx.get(r["api_url"], params={"lat": lat, "lon": lon, "date": day.isoformat(),
                                            "last_date": (day + timedelta(days=1)).isoformat(),
                                            "tz": "Europe/Berlin"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def summarize(raw: dict[str, Any]) -> dict[str, Any]:
    """Aggregiert Stundenwerte über die Arbeitszeit (07–17 Uhr)."""
    cal = settings.rules()["calendar"]
    h0, h1 = int(cal["shift_start"][:2]), int(cal["shift_end"][:2])
    hours = [w for w in raw.get("weather", []) if h0 <= int(w["timestamp"][11:13]) <= h1]
    if not hours:
        return {"available": False}
    temps = [w["temperature"] for w in hours if w.get("temperature") is not None]
    precip = [w.get("precipitation") or 0.0 for w in hours]
    gusts = [w.get("wind_gust_speed") or 0.0 for w in hours]
    conds = [w.get("condition") for w in hours if w.get("condition")]
    cond = max(set(conds), key=conds.count) if conds else None
    src = raw.get("sources", [{}])[0]
    return {
        "available": True,
        "temp_min": min(temps) if temps else None,
        "temp_max": max(temps) if temps else None,
        "temp_7": hours[0].get("temperature"),
        "precip_sum": round(sum(precip), 1),
        "precip_max_h": max(precip),
        "gust_max": max(gusts),
        "condition": cond,
        "station": src.get("station_name"),
        "source": "DWD via Bright Sky",
    }


def assess(s: dict[str, Any]) -> dict[str, Any]:
    r = settings.rules()["weather"]
    if not s.get("available"):
        return {"exceptional": None, "reasons": ["keine Wetterdaten"]}
    reasons = []
    if s["precip_sum"] > r["precipitation_mm_day"]:
        reasons.append(f"Niederschlag {s['precip_sum']} mm > {r['precipitation_mm_day']} mm")
    if s["precip_max_h"] > r["precipitation_mm_hour"]:
        reasons.append(f"Starkregen {s['precip_max_h']} mm/h")
    if s["gust_max"] > r["wind_gust_kmh"]:
        reasons.append(f"Böen {s['gust_max']} km/h > {r['wind_gust_kmh']} km/h")
    if s["temp_min"] is not None and s["temp_min"] < r["temp_min_c"]:
        reasons.append(f"Frost {s['temp_min']} °C < {r['temp_min_c']} °C")
    if s["temp_max"] is not None and s["temp_max"] > r["temp_max_c"]:
        reasons.append(f"Hitze {s['temp_max']} °C")
    return {
        "exceptional": bool(reasons),
        "reasons": reasons or ["im Rahmen der üblichen Witterung – keine Behinderung"],
    }
