#!/bin/bash
# Alle SiteVox-Modelle auf EINER GPU:
#   :8001 vLLM Qwen3-4B-Instruct-2507 (Extraktor)   ~0.18 GPU-Speicher
#   :8002 vLLM Qwen3-8B bf16 (Drafter, kein AWQ)    ~0.30 GPU-Speicher
#   :8003 vLLM Qwen3-VL-4B-Instruct (Vision)        ~0.20 GPU-Speicher
#   :8004 faster-whisper large-v3 (asr_server.py)    Rest
# Backend + Frontend laufen lokal:  bash scripts/cluster/tunnel.sh
#
# Modelle als lokale Ordner (Login-Knoten herunterladen, siehe MODELS unten); vLLM aus VLLM_VENV, ASR aus ASR_VENV.
# Start:   sbatch scripts/cluster/serve_models_single.sbatch
#SBATCH --job-name=sitevox-llm
#SBATCH --gres=gpu:1
#SBATCH --time=18:00:00
#SBATCH --output=data/serve_slurm_%j.log
#SBATCH --export=NONE
set -euo pipefail
unset SLURM_EXPORT_ENV
cd "${SLURM_SUBMIT_DIR}"

KEY_FILE="${HOME}/.config/sitevox/api_key"
[[ -r "${KEY_FILE}" ]] || { echo "API-Key fehlt: ${KEY_FILE}" >&2; exit 1; }
export SITEVOX_LLM_API_KEY="$(<"${KEY_FILE}")"

MODELS="${MODELS:-${WORK}/mmr/models}"
# Achtung: --export=NONE verwirft Variablen aus der Shell → Überschreiben nur per
#   sbatch --export=NONE,EXTRACTOR=/pfad scripts/cluster/serve_models_single.sbatch
EXTRACTOR="${EXTRACTOR:-${MODELS}/Qwen3-4B-Instruct-2507}"
if [[ ! -f "${EXTRACTOR}/config.json" ]]; then  # Fallback: vorhandener HF-Cache (MLinHealth-Projekt)
  for d in "${HOME}"/Abschlussarbeit-multilingual-math-reasoning/MLinHealth-depression-detection/.cache/huggingface/hub/models--Qwen--Qwen3-4B-Instruct-2507/snapshots/*/; do
    [[ -f "${d}config.json" ]] && EXTRACTOR="${d%/}"
  done
fi
DRAFTER="${DRAFTER:-${MODELS}/Qwen3-8B}"
VISION="${VISION:-${MODELS}/Qwen3-VL-4B-Instruct}"
VLLM_PY="${VLLM_VENV:-${HOME}/mmr-env/venv}/bin/python"
ASR_PY="${ASR_VENV:-${WORK}/asr-venv}/bin/python"
for d in "${EXTRACTOR}" "${DRAFTER}" "${VISION}"; do
  [[ -f "${d}/config.json" ]] || { echo "Modell fehlt: ${d}" >&2; exit 1; }
done

# Kein nvcc auf den Knoten → FlashInfer-JIT (Sampling) schlägt fehl; PyTorch-Sampler nutzen
export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export HF_HOME="${HF_HOME:-${WORK}/hf_cache}" TORCH_HOME="${TORCH_HOME:-${WORK}/torch_cache}" TMPDIR="${TMPDIR:-/tmp}"

nvidia-smi --query-gpu=name,memory.total --format=csv
echo "NODE=$(hostname)  ->  lokal: bash scripts/cluster/tunnel.sh $(hostname)"

PIDS=()
trap 'kill "${PIDS[@]}" 2>/dev/null' EXIT
wait_up() {  # $1 Port, $2 PID – auf /health warten, abbrechen wenn der Prozess stirbt
  for _ in $(seq 240); do
    curl -sf "http://127.0.0.1:$1/health" >/dev/null && { echo "Port $1 bereit"; return; }
    kill -0 "$2" 2>/dev/null || { echo "Dienst auf Port $1 abgestürzt – siehe data/serve_*.log" >&2; exit 1; }
    sleep 5
  done
  echo "Port $1 nach 20 min nicht bereit" >&2; exit 1
}

# vLLM nacheinander starten: parallele Speicher-Profilierung auf derselben GPU kollidiert
start_llm() {  # $1 Rolle, $2 Modellordner, $3 gpu-util, $4 Port
  PATH="$(dirname "${VLLM_PY}"):${PATH}" "${VLLM_PY}" scripts/serve_models.py --run --wait --host 0.0.0.0 \
      --roles "$1" --model "$1=$2" --gpu-util "$1=$3" & PIDS+=($!)
  wait_up "$4" "$!"
}
start_llm extractor "${EXTRACTOR}" "${UTIL_EXTRACTOR:-0.18}" 8001
start_llm drafter   "${DRAFTER}"   "${UTIL_DRAFTER:-0.30}"   8002
start_llm vision    "${VISION}"    "${UTIL_VISION:-0.20}"    8003

# faster-whisper aus der bewährten asr-venv; cuBLAS/cuDNN der nvidia-*-cu12 Pakete für CTranslate2 sichtbar machen
NV_LIBS="$("${ASR_PY}" -c 'import glob, os, nvidia; print(":".join(sorted({os.path.dirname(p) for d in nvidia.__path__ for p in glob.glob(os.path.join(d, "*", "lib", "*.so*"))})))' 2>/dev/null || true)"
PATH="$(dirname "${ASR_PY}"):${PATH}" LD_LIBRARY_PATH="${NV_LIBS}:${LD_LIBRARY_PATH:-}" \
SITEVOX_MODE=gpu SITEVOX_DEVICE=cuda SITEVOX_ASR_BACKEND="${ASR_BACKEND:-faster_whisper}" \
    "${ASR_PY}" scripts/cluster/asr_server.py --host 0.0.0.0 --port 8004 > data/serve_asr.log 2>&1 & PIDS+=($!)
wait_up 8004 "$!"

nvidia-smi --query-gpu=memory.used,memory.total --format=csv
echo "Alle Dienste bereit."
wait -n "${PIDS[@]}"   # fällt ein Dienst aus, Job beenden (statt halb zu laufen)
echo "Ein Dienst wurde beendet – siehe data/serve_*.log" >&2
exit 1
