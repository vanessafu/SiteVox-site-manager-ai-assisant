#!/usr/bin/env python3
"""WhisperX-ASR als kleiner HTTP-Dienst auf dem GPU-Knoten (Gegenstück zu asr.backend = "remote").

  SITEVOX_MODE=gpu SITEVOX_ASR_BACKEND=whisperx SITEVOX_LLM_API_KEY=... \\
      python scripts/cluster/asr_server.py --host 0.0.0.0 --port 8004

Liefert dieselbe Struktur wie sitevox.understand.asr.transcribe (Wort-Zeitstempel + Scores, erkannte Sprache).
Audio wird nur in ein privates Temp-Verzeichnis geschrieben und sofort gelöscht; Inhalte werden nicht geloggt.
"""
from __future__ import annotations

import argparse
import hmac
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn  # noqa: E402
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile  # noqa: E402

from sitevox import settings  # noqa: E402
from sitevox.understand import asr  # noqa: E402

API_KEY = os.environ.get("SITEVOX_LLM_API_KEY", "")
ALLOWED = {"auto", *settings.models()["asr"].get("allowed_languages", [])}
_gpu_lock = threading.Lock()  # ein Modell auf einer GPU → Anfragen nacheinander
app = FastAPI(title="SiteVox ASR", docs_url=None, redoc_url=None, openapi_url=None)


def _auth(authorization: Optional[str] = Header(None)) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not API_KEY or not hmac.compare_digest(token, API_KEY):
        raise HTTPException(401, "unauthorized")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "model": settings.models()["asr"]["model"]}


@app.post("/transcribe", dependencies=[Depends(_auth)])
def transcribe(file: UploadFile = File(...), language: str = Form("auto")) -> dict:
    if language not in ALLOWED:
        raise HTTPException(400, f"language muss eine von {sorted(ALLOWED)} sein")
    with tempfile.TemporaryDirectory(prefix="sitevox-asr-") as d:  # Modus 0700
        tmp = Path(d) / Path(file.filename or "audio").name
        tmp.write_bytes(file.file.read())
        with _gpu_lock:
            return asr.transcribe(tmp, language=language)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8004)
    args = ap.parse_args()
    if not API_KEY:
        sys.exit("SITEVOX_LLM_API_KEY fehlt")
    if settings.is_demo() or settings.models()["asr"]["backend"] == "remote":
        sys.exit("Bitte SITEVOX_MODE=gpu und SITEVOX_ASR_BACKEND=whisperx|faster_whisper setzen")
    asr._whisperx_model() if settings.models()["asr"]["backend"] == "whisperx" else asr._fw_model()  # vorladen
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
