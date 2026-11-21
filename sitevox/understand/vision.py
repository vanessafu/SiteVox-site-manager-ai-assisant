"""Foto → strukturierte Beobachtungen (Qwen3-VL-4B-Instruct), nur bei Bedarf geladen.

Rollenteilung:  VLM = "was ist zu sehen" (PhotoAnalysis)  ·  Sprache/Notiz = "warum, wer, seit wann, wie viel"
                ·  Regelwerk (engine/sphere.py) = Risikosphäre und Schreiben.

* backend="openai": vLLM-Server, guided decoding per JSON-Schema (llm.structured – Retry + Pydantic-Validierung)
* backend="transformers": lazy in-process; gleicher Retry/Validierungs-Pfad über llm.structured → generate_local
* Demo-Modus: Fixture data/demo/<projekt>/fixtures/vision/<foto>.json ({"exif": {...}, "base": PhotoAnalysis})

Zusätzlich deterministisch: EXIF-Aufnahmezeit und GPS, Ausschnitte (bbox) als eigene Bilddateien.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Type

from .. import llm, settings
from ..prompts import FOLLOWUP_DEFAULT, VISION_CONTEXT, VISION_PROMPT, followup_questions, out_lang_name
from ..schemas import PhotoAnalysis

log = logging.getLogger(__name__)
_lock = threading.Lock()
_model: dict[str, Any] = {}
# Vorrang für die eine Rückfrage: P0 (Behinderung, Mangel) vor Sicherheit vor P1 (Fortschritt)
CATEGORY_PRIORITY = {"obstruction": 0, "defect": 0, "safety": 1, "progress": 2}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


# ----------------------------------------------------------------------------- EXIF
def _exif_iso(raw: str, tz_hint: Optional[str] = None) -> Optional[str]:
    """'2026:11:20 07:31:00' → '2026-11-20T07:31:00+01:00' (Zeitzone aus tz_hint bzw. lokal)."""
    try:
        dt = datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.fromisoformat(str(raw))
        except ValueError:
            return None
    if dt.tzinfo is None:
        if tz_hint:
            return dt.isoformat(timespec="seconds") + tz_hint
        dt = dt.astimezone()
    return dt.isoformat(timespec="seconds")


def exif_meta(path: Path, tz_hint: Optional[str] = None) -> dict[str, Any]:
    """Liest Aufnahmezeit (DateTimeOriginal vor DateTime) und GPS aus EXIF (falls vorhanden)."""
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
    sub = exif.get_ifd(0x8769) if hasattr(exif, "get_ifd") else {}
    raw = sub.get(0x9003) or tags.get("DateTimeOriginal") or tags.get("DateTime")
    if raw:
        out["taken_at_raw"] = str(raw)
        iso = _exif_iso(str(raw), tz_hint)
        if iso:
            out["taken_at"] = iso
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


# ----------------------------------------------------------------------------- Bilddaten
def _clean_jpeg(path: Path, max_side: int) -> bytes:
    """Neu kodiertes JPEG ohne EXIF (GPS, Geräte-ID) und verkleinert – weniger Daten über den Tunnel."""
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)  # ohne exif= → keine Metadaten
    return buf.getvalue()


def crop(path: Path, bbox: list[int], out: Path, pad: float = 0.04) -> Optional[Path]:
    """Ausschnitt um bbox (relativ 0–1000) als eigene Datei – Beleg ist das Bild, nicht die KI-Beschreibung."""
    try:
        from PIL import Image, ImageOps

        img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    except Exception:  # noqa: BLE001 – Platzhalter/defekte Datei: kein Ausschnitt
        return None
    w, h = img.size
    x1, y1, x2, y2 = bbox
    px, py = pad * w, pad * h
    box = (max(0, int(x1 / 1000 * w - px)), max(0, int(y1 / 1000 * h - py)),
           min(w, int(x2 / 1000 * w + px)), min(h, int(y2 / 1000 * h + py)))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    img.crop(box).save(out, format="JPEG", quality=90)
    return out


# ----------------------------------------------------------------------------- lokales Modell
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


def _to_hf_messages(msgs: list[dict]) -> list[dict]:
    """OpenAI-Format (image_url mit data-URI) → transformers-Chat-Template (type=image)."""
    out = []
    for m in msgs:
        content = m["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        parts = []
        for c in content:
            if c.get("type") == "image_url":
                parts.append({"type": "image", "image": c["image_url"]["url"]})
            else:
                parts.append(c)
        out.append({"role": m["role"], "content": parts})
    return out


def generate_local(msgs: list[dict], schema: Type, *, temperature: float) -> str:
    """Eine Stichprobe mit dem lokalen VL-Modell. Ohne guided decoding steht das JSON-Schema im Prompt;
    Validierung und Retry übernimmt llm.LLM._call."""
    cfg = settings.models()["llm"]["vision"]
    processor, model = _load_transformers()
    hint = {"role": "user", "content": "Antworte ausschließlich mit JSON nach diesem Schema:\n"
            + json.dumps(schema.model_json_schema(), ensure_ascii=False)}
    inputs = processor.apply_chat_template(_to_hf_messages(list(msgs) + [hint]), tokenize=True,
                                           add_generation_prompt=True, return_dict=True,
                                           return_tensors="pt").to(model.device)
    gen_kw: dict[str, Any] = {"max_new_tokens": cfg.get("max_tokens", 1024)}
    if temperature and temperature > 0:
        gen_kw.update(do_sample=True, temperature=temperature)
    out = model.generate(**inputs, **gen_kw)
    gen = out[:, inputs["input_ids"].shape[1]:]
    return processor.batch_decode(gen, skip_special_tokens=True)[0].strip()


# ----------------------------------------------------------------------------- Analyse
def _fallback() -> PhotoAnalysis:
    return PhotoAnalysis(summary="Foto ohne KI-Bildauswertung (kein Modell/Fixture verfügbar).",
                         followup_question=FOLLOWUP_DEFAULT)


def _demo_exif(project_id: str, stem: str) -> dict[str, Any]:
    fx = settings.demo_dir(project_id) / "fixtures" / "vision" / f"{stem}.json"
    if not fx.exists():
        return {}
    return json.loads(fx.read_text(encoding="utf-8")).get("exif", {})


def live_in_demo() -> bool:
    """Demo-Modus, aber Fotos trotzdem mit dem echten VLM: SITEVOX_VISION_LIVE=1 oder live_in_demo = true."""
    import os

    if not settings.is_demo():
        return False
    env = os.environ.get("SITEVOX_VISION_LIVE")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return bool(settings.models()["llm"]["vision"].get("live_in_demo", False))


def analyze(path: Path, project_id: str, *, activities_today: Optional[list[str]] = None,
            fixture_stem: Optional[str] = None,
            tz_hint: Optional[str] = None, out_lang: str = "de") -> dict[str, Any]:
    """Foto → {exif, analysis (PhotoAnalysis), backend, model}. out_lang: Sprache von summary/Rückfrage. Wirft keine Fehler wegen des Modells:
    schlägt das VLM fehl, bleibt das Foto Beleg und die Rückfrage allgemein (analysis_error gesetzt)."""
    path = Path(path)
    cfg = settings.models()["llm"]["vision"]
    meta = exif_meta(path, tz_hint)
    live = live_in_demo()
    if settings.is_demo():
        meta = {**meta, **_demo_exif(project_id, fixture_stem or path.stem)}
    ctx = VISION_CONTEXT.format(activities=", ".join(activities_today)) if activities_today else ""
    prompt = VISION_PROMPT.format(context=ctx, out_lang=out_lang_name(out_lang))
    content: list[dict] = [{"type": "text", "text": prompt}]
    if live or not settings.is_demo():
        b64 = base64.b64encode(_clean_jpeg(path, cfg.get("max_image_side", 1536))).decode()
        content.insert(0, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    msgs = [{"role": "user", "content": content}]
    out: dict[str, Any] = {"exif": meta, "backend": "replay" if settings.is_demo() and not live
                           else cfg.get("backend"), "model": cfg["model"]}
    if live:  # Demo, aber echtes VLM – bei jedem Fehler zurück auf Fixture/Fallback, damit die Demo nie hängt
        try:
            res = llm.get("vision")._call(PhotoAnalysis, msgs, n=1, temperature=cfg.get("temperature", 0.1))[0]
            out["analysis"] = res.model_dump()
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("Live-VLM im Demo-Modus fehlgeschlagen, nutze Replay: %s", e)
            out["backend"], out["live_error"] = "replay", str(e)[:300]
    try:
        res = llm.get("vision").structured(PhotoAnalysis, msgs, n=1, temperature=cfg.get("temperature", 0.1),
                                           fixture=(project_id, f"vision/{fixture_stem or path.stem}"), fallback=_fallback)[0]
    except llm.LLMError as e:
        log.warning("Fotoanalyse fehlgeschlagen: %s", e)
        res, out["analysis_error"] = _fallback(), str(e)[:300]
    out["analysis"] = res.model_dump()
    return out


def primary_observation(analysis: dict) -> Optional[int]:
    """Index des Befunds, nach dem gefragt wird (P0 vor P1, dann Schwere, dann visuelle Sicherheit)."""
    obs = analysis.get("observations") or []
    if not obs:
        return None
    return min(range(len(obs)), key=lambda i: (CATEGORY_PRIORITY.get(obs[i]["category"], 9),
                                               SEVERITY_RANK.get(obs[i].get("severity"), 9),
                                               -float(obs[i].get("visual_conf") or 0)))


def followup(analysis: dict, out_lang: str = "de") -> dict[str, Any]:
    """Genau eine Rückfrage, deterministisch aus dem wichtigsten Befund. Die VLM-Frage dient nur als Rückfall
    für 'other' – so fragt die App immer, was das Regelwerk braucht (Verursacher, Beginn, eigene Leistung, Menge)."""
    questions, default = followup_questions(out_lang)
    i = primary_observation(analysis)
    if i is None:
        return {"question": default, "category": None, "subtype": None, "observation": None}
    o = analysis["observations"][i]
    q = questions.get(o["subtype"])
    if o["subtype"] == "other" or not q:
        q = (analysis.get("followup_question") or "").strip() or default
    return {"question": q, "category": o["category"], "subtype": o["subtype"], "observation": i,
            "wants_detail_photo": o["category"] == "defect"}
