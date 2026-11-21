"""Foto → sachliche Beschreibung (Qwen3-VL-4B-Instruct), nur bei Bedarf geladen.

Zusätzlich deterministisch: EXIF-Zeitstempel und GPS (für Anlagen im Export).
"""
from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .. import settings
from ..prompts import VISION_PROMPT

_lock = threading.Lock()
_model: dict[str, Any] = {}


def exif_meta(path: Path) -> dict[str, Any]:
    """Liest Aufnahmezeit und GPS aus EXIF (falls vorhanden)."""
    try:
        from PIL import ExifTags, Image
    except ImportError:
        return {}
    try:
        img = Image.open(path)
        exif = img.getexif()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, Any] = {}
    tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
    if "DateTime" in tags:
        out["taken_at"] = str(tags["DateTime"])
    gps = exif.get_ifd(0x8825) if hasattr(exif, "get_ifd") else {}
    if gps and 2 in gps and 4 in gps:
        def deg(v):
            d, m, s = (float(x) for x in v)
            return d + m / 60 + s / 3600

        lat, lon = deg(gps[2]), deg(gps[4])
        if gps.get(1) == "S":
            lat = -lat
        if gps.get(3) == "W":
            lon = -lon
        out["gps"] = {"lat": round(lat, 6), "lon": round(lon, 6)}
    return out


def _load_transformers():
    cfg = settings.models()["llm"]["vision"]
    with _lock:
        if "model" not in _model:
            from transformers import AutoModelForImageTextToText, AutoProcessor  # type: ignore

            _model["processor"] = AutoProcessor.from_pretrained(cfg["model"])
            _model["model"] = AutoModelForImageTextToText.from_pretrained(
                cfg["model"], torch_dtype="auto", device_map="auto")
        _model["last_used"] = time.time()
    return _model["processor"], _model["model"]


def maybe_unload() -> None:
    """Gibt VRAM frei, wenn das VL-Modell länger ungenutzt war (lazy_load)."""
    cfg = settings.models()["llm"]["vision"]
    with _lock:
        if "model" in _model and time.time() - _model.get("last_used", 0) > cfg.get("unload_after_s", 300):
            _model.clear()
            try:
                import torch  # type: ignore

                torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001
                pass


def _describe_transformers(path: Path) -> str:
    cfg = settings.models()["llm"]["vision"]
    processor, model = _load_transformers()
    messages = [{"role": "user", "content": [{"type": "image", "image": str(path)},
                                             {"type": "text", "text": VISION_PROMPT}]}]
    inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                           return_dict=True, return_tensors="pt").to(model.device)
    out = model.generate(**inputs, max_new_tokens=cfg.get("max_tokens", 512))
    gen = out[:, inputs["input_ids"].shape[1]:]
    return processor.batch_decode(gen, skip_special_tokens=True)[0].strip()


def _clean_jpeg(path: Path, max_side: int) -> bytes:
    """Neu kodiertes JPEG ohne EXIF (GPS, Geräte-ID) und verkleinert – weniger Daten über den Tunnel."""
    import io

    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)  # ohne exif= → keine Metadaten
    return buf.getvalue()


def _describe_openai(path: Path) -> str:
    from openai import OpenAI

    cfg = settings.models()["llm"]["vision"]
    b64 = base64.b64encode(_clean_jpeg(Path(path), cfg.get("max_image_side", 1536))).decode()
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg.get("api_key", "local"))
    r = client.chat.completions.create(
        model=cfg.get("served_name", cfg["model"]), temperature=cfg.get("temperature", 0.1),
        max_tokens=cfg.get("max_tokens", 512),
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": VISION_PROMPT}]}],
    )
    return r.choices[0].message.content.strip()


def describe(path: Path, project_id: Optional[str] = None) -> dict[str, Any]:
    path = Path(path)
    meta = exif_meta(path)
    if settings.is_demo():
        fx = settings.demo_dir(project_id or "BV-RIEM") / "fixtures" / "vision" / f"{path.stem}.json"
        d = json.loads(fx.read_text(encoding="utf-8")) if fx.exists() else {"description": "Foto ohne Beschreibung"}
        return {**meta, **d, "backend": "replay"}
    cfg = settings.models()["llm"]["vision"]
    text = _describe_transformers(path) if cfg.get("backend") == "transformers" else _describe_openai(path)
    return {**meta, "description": text, "backend": cfg.get("backend"), "model": cfg["model"]}
