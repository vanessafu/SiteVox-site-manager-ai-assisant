"""DSGVO: Gesichter vor dem Export automatisch verpixeln; EXIF wird beim Neuschreiben entfernt
(Zeit und GPS stehen stattdessen in der Bildunterschrift der Anlage)."""
from __future__ import annotations

from pathlib import Path


def blur_faces(src: Path, dst: Path) -> dict:
    try:
        import cv2  # type: ignore
    except ImportError:
        import shutil

        shutil.copy(src, dst)
        return {"faces": None, "note": "OpenCV fehlt – nicht anonymisiert"}
    img = cv2.imread(str(src))
    if img is None:
        raise ValueError(f"Bild nicht lesbar: {src}")
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV >= 5 ohne Haar-Kaskaden → opencv<5 installieren
        import shutil

        shutil.copy(src, dst)
        return {"faces": None, "note": "Gesichtserkennung nicht verfügbar (opencv<5 benötigt) – manuell prüfen"}
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
    for (x, y, w, h) in faces:
        pad = int(0.15 * w)
        x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(img.shape[1], x + w + pad), min(img.shape[0], y + h + pad)
        roi = img[y0:y1, x0:x1]
        small = cv2.resize(roi, (max(1, (x1 - x0) // 12), max(1, (y1 - y0) // 12)))
        img[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dst), img)
    return {"faces": int(len(faces))}
