#!/bin/bash
# recover.sh — agent startup recovery script.
#
# Any agent (Claude, Codex, Cursor, etc.) should source this on startup:
#   source .agent-coordination/recover.sh
#
# It automatically:
#   1. Detects zombie agents (expired heartbeats)
#   2. Finds orphaned milestones
#   3. Reports next steps
#   4. Starts a background heartbeat

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COORD_PY="${COORD_DIR}/coord.py"
AGENT_ID="${AGENT_ID:-$(hostname)-$$}"

echo "[recover] agent-id: ${AGENT_ID}"

# Register if new
python3 "${COORD_PY}" register-agent "${AGENT_ID}" --type "opencode" >/dev/null 2>&1 || true

# Run recovery
python3 "${COORD_PY}" recover --agent-id "${AGENT_ID}"

# Start background heartbeat (every 120s)
(
  while true; do
    python3 "${COORD_PY}" heartbeat "${AGENT_ID}" >/dev/null 2>&1
    sleep 120
  done
) &
HEARTBEAT_PID=$!
export HEARTBEAT_PID

echo "[recover] heartbeat started (pid=${HEARTBEAT_PID}, interval=120s)"
echo "[recover] done — continuing work"