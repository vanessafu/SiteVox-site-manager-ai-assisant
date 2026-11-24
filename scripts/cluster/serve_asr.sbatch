#!/bin/bash
# Nur ASR (faster-whisper large-v3) als HTTP-Dienst :8004 auf einer GPU – Gegenstück zu asr.backend = "remote".
# Backend + Frontend laufen lokal und erreichen den Dienst über:  PORTS=8004 bash scripts/cluster/tunnel.sh <knoten>
#
# Einmalig (Login-Knoten): API-Key anlegen
#   mkdir -p ~/.config/sitevox && openssl rand -hex 24 > ~/.config/sitevox/api_key && chmod 600 ~/.config/sitevox/api_key
# Start:   sbatch scripts/cluster/serve_asr.sbatch        (ASR_BACKEND=whisperx sbatch … für WhisperX)
# Knoten:  squeue -u $USER -n sitevox-asr -h -o %N
#SBATCH --job-name=sitevox-asr
#SBATCH --gres=gpu:1
#SBATCH --time=08:00:00
#SBATCH --output=data/serve_asr_slurm_%j.log
#SBATCH --export=NONE
set -euo pipefail
unset SLURM_EXPORT_ENV
cd "${SLURM_SUBMIT_DIR}"

KEY_FILE="${HOME}/.config/sitevox/api_key"
[[ -r "${KEY_FILE}" ]] || { echo "API-Key fehlt: ${KEY_FILE}" >&2; exit 1; }
export SITEVOX_LLM_API_KEY="$(<"${KEY_FILE}")"

PY="${ASR_VENV:-${WORK}/asr-venv}/bin/python"
export HF_HOME="${HF_HOME:-${WORK}/hf_cache}" TORCH_HOME="${TORCH_HOME:-${WORK}/torch_cache}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 TMPDIR="${TMPDIR:-/tmp}"
export SITEVOX_MODE=gpu SITEVOX_DEVICE=cuda SITEVOX_ASR_BACKEND="${ASR_BACKEND:-faster_whisper}"
export PATH="$(dirname "${PY}"):${PATH}"
# cuBLAS/cuDNN aus den pip-Paketen (nvidia-*-cu12) für CTranslate2 auffindbar machen
NV_LIBS="$("${PY}" -c 'import glob, os, nvidia; print(":".join(sorted({os.path.dirname(p) for d in nvidia.__path__ for p in glob.glob(os.path.join(d, "*", "lib", "*.so*"))})))' 2>/dev/null || true)"
[[ -n "${NV_LIBS}" ]] && export LD_LIBRARY_PATH="${NV_LIBS}:${LD_LIBRARY_PATH:-}"

nvidia-smi --query-gpu=name,memory.total --format=csv
echo "NODE=$(hostname) BACKEND=${SITEVOX_ASR_BACKEND}  ->  lokal: PORTS=8004 bash scripts/cluster/tunnel.sh $(hostname)"
exec "${PY}" scripts/cluster/asr_server.py --host 0.0.0.0 --port 8004
