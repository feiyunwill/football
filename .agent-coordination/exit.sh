#!/bin/bash
# exit.sh — graceful agent exit.
# Source this before finishing a session:
#   source .agent-coordination/exit.sh

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COORD_PY="${COORD_DIR}/coord.py"
AGENT_ID="${AGENT_ID:-$(hostname)-$$}"

if [ -n "$HEARTBEAT_PID" ]; then
  kill "$HEARTBEAT_PID" 2>/dev/null || true
  echo "[exit] heartbeat stopped"
fi

echo "[exit] agent ${AGENT_ID} done"