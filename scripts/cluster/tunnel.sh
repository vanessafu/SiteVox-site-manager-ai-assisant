#!/usr/bin/env bash
# LOKAL ausführen: leitet localhost:8001–8004 (LLMs, Vision, ASR) über Jump-Host → Login-Knoten auf den GPU-Knoten weiter.
#   bash scripts/cluster/tunnel.sh <knoten>            # Knoten aus `squeue -u $USER -n sitevox-llm`
#   CLUSTER_USER=CLUSTER_USER bash scripts/cluster/tunnel.sh # Knoten automatisch ermitteln
set -euo pipefail
CLUSTER_USER="${CLUSTER_USER:-$USER}"
JUMP="${CLUSTER_USER}@JUMP_HOST"
LOGIN="${CLUSTER_USER}@LOGIN_HOST"
PORTS="${PORTS:-8001 8002 8003 8004}"
SSH_OPTS=(-o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -o ControlMaster=auto
          -o ControlPath="${HOME}/.ssh/cm-%r@%h:%p" -o ControlPersist=10m)

NODE="${1:-}"
if [[ -z "${NODE}" ]]; then
  NODE="$(ssh "${SSH_OPTS[@]}" -J "${JUMP}" "${LOGIN}" "squeue -u ${CLUSTER_USER} -n sitevox-llm -t R -h -o %N" | head -1)"
  [[ -n "${NODE}" ]] || { echo "Kein laufender sitevox-llm Job." >&2; exit 1; }
fi

FWD=()
for p in ${PORTS}; do FWD+=(-L "127.0.0.1:${p}:${NODE}:${p}"); done
echo "Tunnel → ${NODE}: ${PORTS} (Strg+C beendet)"
exec ssh -N "${SSH_OPTS[@]}" -J "${JUMP}" "${FWD[@]}" "${LOGIN}"
