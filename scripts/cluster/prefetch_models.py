#!/usr/bin/env python3
"""Einmalig auf dem LOGIN-Knoten (hat Internet): alle Gewichte in $WORK cachen,
damit der GPU-Job komplett offline läuft (HF_HUB_OFFLINE=1).

  source $WORK/sitevox-venv/bin/activate
  HF_HOME=$WORK/hf_cache TORCH_HOME=$WORK/torch_cache python scripts/cluster/prefetch_models.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from huggingface_hub import snapshot_download  # noqa: E402

from sitevox import settings  # noqa: E402

m = settings.models()
for role in ("extractor", "drafter", "vision"):
    cfg = m["llm"][role]
    repo = cfg.get("awq_repo") if role == "drafter" and cfg.get("awq_repo") else cfg["model"]
    print("↓", repo, flush=True)
    snapshot_download(repo)

# WhisperX: CTranslate2-Modell + wav2vec2-Alignment je Sprache (de/en via torchaudio → TORCH_HOME)
import whisperx  # noqa: E402

c = m["asr"]
print("↓ whisper", c["model"], flush=True)
whisperx.load_model(c["model"], "cpu", compute_type="int8")
for lang in c.get("allowed_languages", ["de"]):
    print("↓ align", lang, flush=True)
    whisperx.load_align_model(language_code=lang, device="cpu")
print("fertig – Job kann mit HF_HUB_OFFLINE=1 laufen")
