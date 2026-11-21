#!/bin/bash
# SiteVox-Modelle auf einem GPU-Knoten (cluster), 2 GPUs:
#   GPU 0: vLLM Qwen3-4B Extraktor :8001 + Qwen3-8B-AWQ Drafter :8002
#   GPU 1: vLLM Qwen3-VL-4B Vision :8003 + WhisperX large-v3 ASR :8004
# Backend + Frontend laufen lokal und erreichen die Dienste über scripts/cluster/tunnel.sh.
#
# Einmalig (Login-Knoten):
#   mkdir -p ~/.config/sitevox && openssl rand -hex 24 > ~/.config/sitevox/api_key && chmod 600 ~/.config/sitevox/api_key
#   python -m venv $WORK/sitevox-venv && $WORK/sitevox-venv/bin/pip install -r requirements-gpu.txt
#   HF_HOME=$WORK/hf_cache TORCH_HOME=$WORK/torch_cache $WORK/sitevox-venv/bin/python scripts/cluster/prefetch_models.py
# Start:   sbatch scripts/cluster/serve_models.sbatch
# Knoten:  squeue -u $USER -n sitevox-llm -h -o %N
#SBATCH --job-name=sitevox-llm
#SBATCH --partition=gpu
#SBATCH --gres=gpu:2
#SBATCH --time=08:00:00
#SBATCH --output=data/serve_slurm_%j.log
#SBATCH --export=NONE
set -euo pipefail
unset SLURM_EXPORT_ENV

cd "${SLURM_SUBMIT_DIR}"
KEY_FILE="${HOME}/.config/sitevox/api_key"
[[ -r "${KEY_FILE}" ]] || { echo "API-Key fehlt: ${KEY_FILE}" >&2; exit 1; }
export SITEVOX_LLM_API_KEY="$(<"${KEY_FILE}")"

source "${SITEVOX_VENV:-${WORK}/sitevox-venv}/bin/activate"

# Keine Telemetrie, komplett offline (Gewichte vorher mit prefetch_models.py laden)
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 HF_HUB_DISABLE_TELEMETRY=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export HF_HOME="${HF_HOME:-${WORK}/hf_cache}" TORCH_HOME="${TORCH_HOME:-${WORK}/torch_cache}"
# Audio-Temp-Dateien knotenlokal statt auf geteiltem Dateisystem
export TMPDIR="${TMPDIR:-/tmp}"

echo "NODE=$(hostname)  ->  lokal: bash scripts/cluster/tunnel.sh $(hostname)"

PIDS=()
CUDA_VISIBLE_DEVICES=0 python scripts/serve_models.py --run --wait --host 0.0.0.0 \
    --roles extractor,drafter --gpu-util extractor=0.35 --gpu-util drafter=0.55 & PIDS+=($!)
CUDA_VISIBLE_DEVICES=1 python scripts/serve_models.py --run --wait --host 0.0.0.0 \
    --roles vision --gpu-util vision=0.55 & PIDS+=($!)
CUDA_VISIBLE_DEVICES=1 SITEVOX_MODE=gpu SITEVOX_DEVICE=cuda SITEVOX_ASR_BACKEND=whisperx \
    python scripts/cluster/asr_server.py --host 0.0.0.0 --port 8004 > data/serve_asr.log 2>&1 & PIDS+=($!)

trap 'kill "${PIDS[@]}" 2>/dev/null' EXIT
wait -n "${PIDS[@]}"   # fällt ein Dienst aus, Job beenden (statt halb zu laufen)
echo "Ein Dienst wurde beendet – siehe data/serve_*.log" >&2
exit 1
