#!/bin/bash
# Nur Eingaben erzeugen (Notizen, Fotos mit Zufallsnamen/EXIF, Sprachnotizen per XTTS + Lärm + Opus), ohne LLMs.
#   sbatch --export=ALL scripts/cluster/scenario_inputs.sbatch            # Serie 23.–26.11., de/en/pl/tr
#   SCENARIOS="data/demo/scenario/….json" SNR_OFFSET=10 sbatch --export=ALL scripts/cluster/scenario_inputs.sbatch
#SBATCH --job-name=sitevox-inputs
#SBATCH --gres=gpu:1
#SBATCH --time=01:30:00
#SBATCH --output=data/inputs_slurm_%j.log
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
TTS="${WORK}/tts-venv/bin"
export HF_HOME="${WORK}/hf_cache" TORCH_HOME="${WORK}/torch_cache" TTS_HOME="${WORK}/tts_cache" COQUI_TOS_AGREED=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
SCENARIOS="${SCENARIOS:-$(ls data/demo/scenario/scenario_SCN-*_2026-*_{de,en,pl,tr}.json 2>/dev/null | sort | tr '\n' ' ')}"
for SC in ${SCENARIOS}; do
  echo "=== ${SC}"
  PATH="${TTS}:${PATH}" "${TTS}/python" scripts/data/scenario/make_scenario_inputs.py "${SC}" \
      --p-accent "${P_ACCENT:-0.6}" ${SNR_OFFSET:+--snr-offset "${SNR_OFFSET}"} || echo "✗ ${SC} fehlgeschlagen"
done
echo fertig
