"""Texterkennung in Bildern (Fotos, gescannte Seiten) – CPU, ohne GPU (RapidOCR / ONNX Runtime).

Modell: PP-OCRv5 latin (erkennt deutsche Umlaute). Wird beim ersten Aufruf geladen (~1 s) und
von modelscope.cn heruntergeladen, falls noch nicht vorhanden. Optional: fehlt `rapidocr`,
liefert image_text() einen leeren String.
Abschalten: SITEVOX_OCR=0 (z. B. für schnelle Tests).
"""
from __future__ import annotations

import io
import logging
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Union

log = logging.getLogger(__name__)
_lock = threading.Lock()
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic"}


def enabled() -> bool:
    if os.environ.get("SITEVOX_OCR", "1") == "0":
        return False
    try:
        import rapidocr  # noqa: F401  # type: ignore
    except ImportError:
        return False
    return True


@lru_cache(maxsize=1)
def _engine():
    from rapidocr import LangDet, LangRec, ModelType, OCRVersion, RapidOCR  # type: ignore

    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    return RapidOCR(params={
        "Det.ocr_version": OCRVersion.PPOCRV5, "Det.lang_type": LangDet.MULTI, "Det.model_type": ModelType.MOBILE,
        "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.lang_type": LangRec.LATIN, "Rec.model_type": ModelType.MOBILE,
    })


def _lines(boxes, txts, scores, min_score: float) -> list[str]:
    """Wortboxen zu Zeilen zusammenfassen (gleiche Höhe → eine Zeile, links nach rechts)."""
    items = []
    for b, t, s in zip(boxes, txts, scores):
        if s < min_score or not t.strip():
            continue
        ys = [p[1] for p in b]
        xs = [p[0] for p in b]
        items.append((sum(ys) / len(ys), max(ys) - min(ys), min(xs), t.strip()))
    items.sort()
    lines: list[list[tuple]] = []
    for it in items:
        if lines and abs(it[0] - lines[-1][0][0]) < max(it[1], lines[-1][0][1]) * 0.6:
            lines[-1].append(it)
        else:
            lines.append([it])
    return [" ".join(w[3] for w in sorted(line, key=lambda w: w[2])) for line in lines]


def image_text(src: Union[str, Path, bytes], min_score: float = 0.6) -> str:
    """Erkannter Text eines Bildes, zeilenweise. Leerer String, wenn OCR nicht verfügbar ist."""
    if not enabled():
        return ""
    try:
        if isinstance(src, (bytes, bytearray)):
            from PIL import Image

            img = Image.open(io.BytesIO(src)).convert("RGB")
            import numpy as np

            src = np.array(img)[:, :, ::-1]  # RGB → BGR
        else:
            src = str(src)
        with _lock:
            r = _engine()(src)
        if not r or r.txts is None:
            return ""
        return "\n".join(_lines(r.boxes, r.txts, r.scores, min_score))
    except Exception as e:  # noqa: BLE001 – OCR ist eine Zusatzquelle, darf nichts blockieren
        log.warning("OCR fehlgeschlagen: %s", e)
        return ""
