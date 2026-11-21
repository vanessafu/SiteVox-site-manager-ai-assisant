#!/bin/bash
# TTS-Daten (XTTS-v2) auf einer A100-80GB (NHR@FAU Alex): Demo-Memos + Szenarien → Baustellenlärm-Mischungen.
# XTTS braucht nur ~4 GB VRAM – mit "--partition=a40 --gres=gpu:a40:1" (ohne -C) startet der Job oft schneller.
#
# Einmalig (Login-Knoten, hat Internet):
#   module load python/3.12-base && python3 -m venv $WORK/tts-venv
#   $WORK/tts-venv/bin/pip install "coqui-tts>=0.26" six soundfile librosa
#   $WORK/tts-venv/bin/pip install "torch==2.8.*" "torchaudio==2.8.*" --index-url https://download.pytorch.org/whl/cu128
#     (torch ≥ 2.9 verlangt torchcodec + FFmpeg-Bibliotheken)
#   HF_HOME=$WORK/hf_cache $WORK/tts-venv/bin/python scripts/data/audio/tts_synthesize.py --prefetch
#   $WORK/tts-venv/bin/python scripts/data/audio/download_data.py      # Lärm + Common-Voice-Akzente → data/raw
# Start:  sbatch scripts/cluster/tts.sbatch      (SCENARIOS=… sbatch … für ein anderes Szenario-Set)
#SBATCH --job-name=sitevox-tts
#SBATCH --partition=a100
#SBATCH --gres=gpu:a100:1
#SBATCH --constraint=a100_80
#SBATCH --time=02:00:00
#SBATCH --output=data/tts_slurm_%j.log
#SBATCH --export=NONE
set -euo pipefail
unset SLURM_EXPORT_ENV
cd "${SLURM_SUBMIT_DIR}"

PY="${TTS_VENV:-${WORK}/tts-venv}/bin/python"
export HF_HOME="${HF_HOME:-${WORK}/hf_cache}" TTS_HOME="${TTS_HOME:-${WORK}/tts_cache}"
export HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 COQUI_TOS_AGREED=1 TMPDIR="${TMPDIR:-/tmp}"
SCENARIOS="${SCENARIOS:-evaluation/data/scenarios.jsonl}"
[[ -f "${SCENARIOS}" ]] || SCENARIOS=evaluation/data/scenarios.example.jsonl
CLONE=(); [[ -d data/raw/speech/de_cv ]] && CLONE=(--clone-from data/raw/speech/de_cv)
NOISE=(); [[ -d data/raw/noise ]] || NOISE=(--synthetic-noise)

nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
"${PY}" -c "import torch; print('torch', torch.__version__, 'cuda ok:', torch.cuda.is_available())"

# 1) Demo-Memos mit echter Stimme, danach Demo-Daten neu (behält die WAVs, passt Fixture-Zeiten an)
"${PY}" scripts/data/audio/tts_synthesize.py --demo
"${PY}" scripts/make_demo_data.py || echo "make_demo_data.py fehlgeschlagen (openpyxl im venv?) – lokal erneut ausführen"

# 2) Szenarien: 2 Studio-Stimmen + je Akzent ein CV-Stimmklon (nur DEV)
"${PY}" scripts/data/audio/tts_synthesize.py --scenarios "${SCENARIOS}" "${CLONE[@]}" --out data/asr_eval/clean

# 3) Lärm: 20/10/5/0 dB + reine Lärm-/Stille-Clips → data/asr_eval/noisy/manifest.jsonl für eval_asr.py
"${PY}" scripts/data/audio/sythesize_noise_data.py --manifest data/asr_eval/clean/manifest.jsonl \
    --out data/asr_eval/noisy "${NOISE[@]}"
# Echte CV-Akzentclips (test-tauglich, menschliche Transkripte) mit demselben Lärm
if [[ -d data/raw/speech/de_cv ]]; then
  "${PY}" scripts/data/audio/sythesize_noise_data.py --speech data/raw/speech/de_cv --out data/asr_eval/noisy_cv \
      --noise-only 0 --silence 0 "${NOISE[@]}"
fi
echo "fertig: data/asr_eval/{clean,noisy,noisy_cv}/manifest.jsonl"
