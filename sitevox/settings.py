"""Lädt config/models.toml, config/rules.toml und config/baseline.yaml."""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("SITEVOX_ROOT", Path(__file__).resolve().parents[1]))
CONFIG_DIR = ROOT / "config"


def _load_toml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, "rb") as f:
        return tomllib.load(f)


@lru_cache
def models() -> dict[str, Any]:
    cfg = _load_toml("models.toml")
    if os.environ.get("SITEVOX_MODE"):
        cfg["runtime"]["mode"] = os.environ["SITEVOX_MODE"]
    return cfg


@lru_cache
def rules() -> dict[str, Any]:
    return _load_toml("rules.toml")


@lru_cache
def baseline() -> dict[str, Any]:
    with open(CONFIG_DIR / "baseline.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def mode() -> str:
    return models()["runtime"]["mode"]


def is_demo() -> bool:
    return mode() == "demo"


def data_dir() -> Path:
    p = Path(os.environ.get("SITEVOX_DATA", ROOT / models()["runtime"]["data_dir"]))
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    if os.environ.get("SITEVOX_DB"):
        return Path(os.environ["SITEVOX_DB"])
    return ROOT / models()["runtime"]["db_path"]


def demo_dir(project_id: str = "BV-RIEM") -> Path:
    return ROOT / "data" / "demo" / project_id


def project_cfg(project_id: str) -> dict[str, Any]:
    """Projekt-Stammdaten: in der App bearbeitete Fassung (SQLite) vor baseline.yaml."""
    try:
        from . import store  # lazy – store importiert settings

        d = store.get("projects", project_id)
        if d and d.get("client"):
            return d
    except Exception:  # noqa: BLE001 – DB evtl. noch nicht angelegt
        pass
    for p in baseline()["projects"]:
        if p["id"] == project_id:
            return p
    raise KeyError(project_id)


def project_files_dir(project_id: str, date: str) -> Path:
    """Ablage /data/{project}/{date}/ für Rohdateien."""
    p = data_dir() / project_id / date
    p.mkdir(parents=True, exist_ok=True)
    return p
