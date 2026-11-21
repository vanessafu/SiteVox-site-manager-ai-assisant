#!/usr/bin/env bash
# LOKAL ausführen: leitet localhost:8001–8004 (LLMs, Vision, ASR) über csnhr → alex auf den GPU-Knoten weiter.
#   bash scripts/cluster/tunnel.sh a0123            # Knoten aus `squeue -u $USER -n sitevox-llm`
#   NHR_USER=b279bb39 bash scripts/cluster/tunnel.sh # Knoten automatisch ermitteln
set -euo pipefail
NHR_USER="${NHR_USER:-$USER}"
JUMP="${NHR_USER}@csnhr.nhr.fau.de"
LOGIN="${NHR_USER}@alex.nhr.fau.de"
PORTS="${PORTS:-8001 8002 8003 8004}"
SSH_OPTS=(-o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -o ControlMaster=auto
          -o ControlPath="${HOME}/.ssh/cm-%r@%h:%p" -o ControlPersist=10m)

NODE="${1:-}"
if [[ -z "${NODE}" ]]; then
  NODE="$(ssh "${SSH_OPTS[@]}" -J "${JUMP}" "${LOGIN}" "squeue -u ${NHR_USER} -n sitevox-llm -t R -h -o %N" | head -1)"
  [[ -n "${NODE}" ]] || { echo "Kein laufender sitevox-llm Job." >&2; exit 1; }
fi

FWD=()
for p in ${PORTS}; do FWD+=(-L "127.0.0.1:${p}:${NODE}:${p}"); done
echo "Tunnel → ${NODE}: ${PORTS} (Strg+C beendet)"
exec ssh -N "${SSH_OPTS[@]}" -J "${JUMP}" "${FWD[@]}" "${LOGIN}"
