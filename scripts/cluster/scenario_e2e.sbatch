#!/bin/bash
# Ende-zu-Ende-Test eines Gold-Szenarios auf EINER GPU:
#   1) Eingaben erzeugen (XTTS + Lärm, Fotos anonymisiert)          – tts-venv
#   2) vLLM (vorhandene Umgebung ~/mmr-env/venv, vLLM 0.32): Qwen3-4B-Instruct-2507 (Extraktion, HF-Cache) ·
#      Qwen3-8B (Schreiben) und Qwen3-VL-4B-Instruct (Fotos) aus $WORK/mmr/models
#   3) ASR-Dienst WhisperX large-v3 (wie produktiv, backend=remote) – asr-venv; Pipeline ebenfalls asr-venv
#   4) Vortag 20.11. per Demo-Replay als Historie, dann Szenario-Tag mit echten Modellen (isolierte DB)
#   5) Auswertung gegen gold.json (evaluation/eval_scenario.py)
# Start:  SCENARIOS="data/demo/scenario/scenario_SCN-RIEM-0016_de.json …" sbatch --export=ALL scripts/cluster/scenario_e2e.sbatch
#         (Standard: alle data/demo/scenario/*.json; Dienste werden einmal gestartet, jedes Szenario mit eigener DB)
#SBATCH --job-name=sitevox-e2e
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --constraint=gpu
#SBATCH --time=05:00:00
#SBATCH --output=data/e2e_slurm_%j.log
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"

SCENARIOS="${SCENARIOS:-${SCENARIO:-$(ls data/demo/scenario/scenario_*.json | tr '\n' ' ')}}"
LOGDIR="data/scenario_runs/job_${SLURM_JOB_ID}"
TTS="${WORK}/tts-venv/bin"; ASR="${WORK}/asr-venv/bin"
SVX="${ASR}"                                        # Pipeline + serve_models.py (Projektabhängigkeiten)
VLLM_BIN="${VLLM_VENV:-${HOME}/mmr-env/venv}/bin"   # nur das vllm-CLI
MODELS="${WORK}/mmr/models"
export HF_HOME="${WORK}/hf_cache" TORCH_HOME="${WORK}/torch_cache" TTS_HOME="${WORK}/tts_cache"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1
export COQUI_TOS_AGREED=1 TMPDIR="${TMPDIR:-/tmp}"
# Laufzeit-Caches (vLLM/torch.compile, Triton) nicht ins volle $HOME, sondern knotenlokal
export VLLM_CACHE_ROOT="${TMPDIR}/vllm-cache" TRITON_CACHE_DIR="${TMPDIR}/triton-cache"
export SITEVOX_LLM_API_KEY="$(openssl rand -hex 24)"      # nur für diesen Job, Dienste lauschen auf 127.0.0.1
mkdir -p "${LOGDIR}"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv

# ---------------------------------------------------------------- 1) Eingaben
if [[ "${REGEN_INPUTS:-1}" == 1 ]]; then
  for SC in ${SCENARIOS}; do
    PATH="${TTS}:${PATH}" "${TTS}/python" scripts/data/scenario/make_scenario_inputs.py "${SC}" \
        --photo-time "${PHOTO_TIME:-exif}" --p-accent "${P_ACCENT:-0.6}" --snr-offset "${SNR_OFFSET:--5}"
  done
fi

# ---------------------------------------------------------------- 2+3) Dienste
PIDS=()
cleanup() { kill "${PIDS[@]}" 2>/dev/null || true; }
trap cleanup EXIT
wait_up() {  # $1 URL, $2 Name
  for _ in $(seq 1 180); do
    curl -sf -H "Authorization: Bearer ${SITEVOX_LLM_API_KEY}" "$1" >/dev/null && { echo "✓ $2 bereit"; return 0; }
    sleep 5
  done
  echo "✗ $2 nicht gestartet – siehe ${LOGDIR}/serve_*.log und data/serve_*.log"; exit 1
}
declare -A MODEL=([drafter]="${MODELS}/Qwen3-8B" [vision]="${MODELS}/Qwen3-VL-4B-Instruct")
for spec in extractor:0.20:8001 drafter:0.30:8002 vision:0.25:8003; do
  IFS=: read -r role util port <<< "${spec}"
  OV=(); [[ -n "${MODEL[$role]:-}" ]] && OV=(--model "${role}=${MODEL[$role]}")
  PATH="${VLLM_BIN}:${PATH}" "${SVX}/python" scripts/serve_models.py --run --wait --roles "${role}" \
      --gpu-util "${role}=${util}" "${OV[@]}" > "${LOGDIR}/serve_${role}.log" 2>&1 & PIDS+=($!)
  wait_up "http://127.0.0.1:${port}/v1/models" "vLLM ${role}"
done
PATH="${ASR}:${PATH}" SITEVOX_MODE=gpu SITEVOX_DEVICE=cuda SITEVOX_ASR_BACKEND=whisperx \
    "${ASR}/python" scripts/cluster/asr_server.py --port 8004 > "${LOGDIR}/serve_asr.log" 2>&1 & PIDS+=($!)
wait_up "http://127.0.0.1:8004/health" "ASR"

# ---------------------------------------------------------------- 4+5) je Szenario: Historie, Pipeline, Auswertung
export SITEVOX_RAG_BACKEND=bm25   # asr-venv hat kein chromadb/sentence-transformers; betrifft nur Normzitate
for SC in ${SCENARIOS}; do
  NAME="$(basename "${SC}" .json)"; NAME="${NAME#scenario_}"
  INP="data/raw/scenario_${NAME}"
  RUN="data/scenario_runs/${NAME}_${SLURM_JOB_ID}"
  OUT="outputs/eval/scenario_${NAME}_${SLURM_JOB_ID}"
  mkdir -p "${RUN}" "${OUT}"
  echo "=== ${NAME}"
  (
    export SITEVOX_DATA="${RUN}" SITEVOX_DB="${RUN}/sitevox.db"
    SITEVOX_MODE=demo "${SVX}/python" scripts/seed_demo.py > "${RUN}/seed_history.log" 2>&1
    echo "✓ Historie (20.11., Demo-Replay) geladen"
    SITEVOX_MODE=gpu SITEVOX_DEVICE=cuda SITEVOX_ASR_BACKEND=remote SITEVOX_VISION_BACKEND=openai \
        "${SVX}/python" scripts/run_scenario.py "${INP}" --plan "${SC}" \
        ${OUTPUT_LANGUAGE:+--output-language "${OUTPUT_LANGUAGE}"} > "${RUN}/run.log" 2>&1 \
      && grep -E "→ CAP|Entwurf|Ereignisse," "${RUN}/run.log" | cut -c1-160
    "${SVX}/python" -m evaluation.eval_scenario --run "${RUN}/run_output.json" --inputs "${INP}" \
        --scenario "${SC}" --out "${OUT}" > /dev/null && echo "✓ Auswertung: ${OUT}/summary.md"
  ) || echo "✗ ${NAME} fehlgeschlagen – siehe ${RUN}/run.log"
done
echo "fertig"
