#!/bin/bash
# TTS-Daten (XTTS-v2) auf einer GPU: Demo-Memos + Szenarien → Baustellenlärm-Mischungen.
# XTTS braucht nur ~4 GB VRAM.
#
# Einmalig (Login-Knoten, hat Internet):
#   module load python/3.12-base && python3 -m venv $WORK/tts-venv
#   $WORK/tts-venv/bin/pip install "coqui-tts>=0.26" six soundfile librosa openpyxl faster-whisper "av<16" imageio-ffmpeg
#   ln -sf "$($WORK/tts-venv/bin/python -c 'import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())')" $WORK/tts-venv/bin/ffmpeg
#   HF_HOME=$WORK/hf_cache $WORK/tts-venv/bin/python -c "from faster_whisper.utils import download_model; download_model('medium')"
#   $WORK/tts-venv/bin/pip install "torch==2.8.*" "torchaudio==2.8.*" --index-url https://download.pytorch.org/whl/cu128
#     (torch ≥ 2.9 verlangt torchcodec + FFmpeg-Bibliotheken)
#   HF_HOME=$WORK/hf_cache $WORK/tts-venv/bin/python scripts/data/audio/tts_synthesize.py --prefetch
#   $WORK/tts-venv/bin/python scripts/data/audio/download_data.py      # Lärm + Common-Voice-Akzente → data/raw
# Start:  sbatch scripts/cluster/tts.sbatch      (SCENARIOS=… bzw. DEMO=1 sbatch --export=ALL,DEMO=1 …)
#SBATCH --job-name=sitevox-tts
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --output=data/tts_slurm_%j.log
#SBATCH --export=NONE
set -euo pipefail
unset SLURM_EXPORT_ENV
cd "${SLURM_SUBMIT_DIR}"

PY="${TTS_VENV:-${WORK}/tts-venv}/bin/python"
export HF_HOME="${HF_HOME:-${WORK}/hf_cache}" TTS_HOME="${TTS_HOME:-${WORK}/tts_cache}"
export HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 COQUI_TOS_AGREED=1 TMPDIR="${TMPDIR:-/tmp}"
export PATH="$(dirname "${PY}"):${PATH}"   # ffmpeg (statisch, imageio-ffmpeg) für --codec opus
SCENARIOS="${SCENARIOS:-evaluation/data/scenarios.jsonl}"
[[ -f "${SCENARIOS}" ]] || SCENARIOS=evaluation/data/scenarios.example.jsonl
CLONE=(); [[ -d data/raw/speech/de_cv ]] && CLONE=(--clone-from data/raw/speech/de_cv)
NOISE=(); [[ -d data/raw/noise ]] || NOISE=(--synthetic-noise)

nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
"${PY}" -c "import torch; print('torch', torch.__version__, 'cuda ok:', torch.cuda.is_available())"

# 1) Nur mit DEMO=1: Demo-Memos neu vertonen (ändert versionierte WAVs), danach Demo-Daten neu
if [[ "${DEMO:-0}" == 1 ]]; then
  "${PY}" scripts/data/audio/tts_synthesize.py --demo
  "${PY}" scripts/make_demo_data.py || echo "make_demo_data.py fehlgeschlagen – lokal erneut ausführen"
fi
# Generierte Evaluationsdaten (gitignored) komplett neu, damit keine alten SNR-Dateien liegen bleiben
rm -rf data/asr_eval/clean data/asr_eval/noisy data/asr_eval/noisy_cv

# 2) Szenarien (de/en/pl/tr): 2 Studio-Stimmen + je Akzent (en/pl/tr-L1) 2 CV-Stimmklone, nur DEV.
#    Jede Aufnahme wird mit faster-whisper medium geprüft; Lautbrei → neu (max. 3×), sonst verworfen.
"${PY}" scripts/data/audio/tts_synthesize.py --scenarios "${SCENARIOS}" "${CLONE[@]}" --langs de en pl tr \
    --out data/asr_eval/clean

# 3) Lärm im Handy-Modell: Stimme fest −18 dBFS, Lärm absolut lauter (SNR 15/10/5/0/−5 dB) + Limiter + Opus
#    wie MediaRecorder; dazu reine Lärm-/Stille-Clips → data/asr_eval/noisy/manifest.jsonl für eval_asr.py
"${PY}" scripts/data/audio/sythesize_noise_data.py --manifest data/asr_eval/clean/manifest.jsonl \
    --out data/asr_eval/noisy --level phone --codec opus "${NOISE[@]}"
# Echte CV-Akzentclips (test-tauglich, menschliche Transkripte) mit demselben Lärm
if [[ -d data/raw/speech/de_cv ]]; then
  "${PY}" scripts/data/audio/sythesize_noise_data.py --speech data/raw/speech/de_cv --out data/asr_eval/noisy_cv \
      --level phone --codec opus --noise-only 0 --silence 0 "${NOISE[@]}"
fi
echo "fertig: data/asr_eval/{clean,noisy,noisy_cv}/manifest.jsonl"
