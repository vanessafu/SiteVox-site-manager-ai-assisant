#!/bin/bash
# ASR-Benchmark auf einer GPU: WhisperX large-v3 (Produktiv-Backend) und faster-whisper (echte Wortwahrscheinlichkeit)
# auf TTS-Szenarien (data/asr_eval/noisy) und echten Common-Voice-Akzentclips (data/asr_eval/noisy_cv).
#
# Einmalig (Login-Knoten):
#   module load python/3.12-base && python3 -m venv $WORK/asr-venv
#   $WORK/asr-venv/bin/pip install whisperx matplotlib imageio-ffmpeg -r requirements.txt
#   HF_HOME=$WORK/hf_cache TORCH_HOME=$WORK/torch_cache $WORK/asr-venv/bin/python scripts/cluster/prefetch_models.py --asr-only
# Start:  sbatch scripts/cluster/eval_asr.sbatch          (BACKENDS="whisperx" sbatch … für nur ein Backend)
#SBATCH --job-name=sitevox-eval-asr
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --constraint=gpu
#SBATCH --time=03:00:00
#SBATCH --output=data/eval_asr_slurm_%j.log
#SBATCH --export=NONE
set -euo pipefail
unset SLURM_EXPORT_ENV
cd "${SLURM_SUBMIT_DIR}"

PY="${ASR_VENV:-${WORK}/asr-venv}/bin/python"
export HF_HOME="${HF_HOME:-${WORK}/hf_cache}" TORCH_HOME="${TORCH_HOME:-${WORK}/torch_cache}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 TMPDIR="${TMPDIR:-/tmp}"
export SITEVOX_MODE=gpu SITEVOX_DEVICE=cuda
# whisperx.load_audio ruft das ffmpeg-CLI auf; auf den Knoten nicht installiert → statisches Binary (pip imageio-ffmpeg) im venv:
#   ln -sf "$($PY -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")" $WORK/asr-venv/bin/ffmpeg
export PATH="$(dirname "${PY}"):${PATH}"
# cuDNN aus dem pip-Paket für CTranslate2 (faster-whisper) auffindbar machen
CUDNN_LIB="$("${PY}" -c 'import os, nvidia.cudnn; print(os.path.join(os.path.dirname(nvidia.cudnn.__file__), "lib"))' 2>/dev/null || true)"
[[ -n "${CUDNN_LIB}" ]] && export LD_LIBRARY_PATH="${CUDNN_LIB}:${LD_LIBRARY_PATH:-}"

nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
STAMP="$(date +%Y%m%d)"
for BACKEND in ${BACKENDS:-whisperx faster_whisper}; do
  for SET in noisy noisy_cv; do
    OUT="outputs/eval/asr_${STAMP}/${BACKEND}_${SET}"
    mkdir -p "$(dirname "${OUT}")"; echo "=== ${BACKEND} × ${SET} → ${OUT}"
    SITEVOX_ASR_BACKEND="${BACKEND}" "${PY}" -m evaluation.eval_asr \
        --manifest "data/asr_eval/${SET}/manifest.jsonl" --out "${OUT}" ${LIMIT:+--limit "${LIMIT}"} \
        > "${OUT}.log" 2>&1 || { echo "FEHLER – siehe ${OUT}.log"; tail -20 "${OUT}.log"; }
  done
done
echo "fertig: outputs/eval/asr_${STAMP}/*/summary.md"
