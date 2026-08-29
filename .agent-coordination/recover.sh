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
#   5. Auto-claims available milestones (new)
#   6. Shows project progress (new)

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COORD_PY="${COORD_DIR}/coord.py"
PROJECT_SCRIPTS="${COORD_DIR}/../.project/scripts"
AGENT_ID="${AGENT_ID:-$(hostname)-$$}"

echo "[recover] agent-id: ${AGENT_ID}"

# Register if new
python3 "${COORD_PY}" register-agent "${AGENT_ID}" --type "opencode" >/dev/null 2>&1 || true

# Run recovery
python3 "${COORD_PY}" recover --agent-id "${AGENT_ID}"

# Auto-claim available milestones (new)
if [ -f "${PROJECT_SCRIPTS}/auto_claim.sh" ]; then
  echo "[recover] checking for available milestones..."
  bash "${PROJECT_SCRIPTS}/auto_claim.sh" "${AGENT_ID}" 2>/dev/null || true
fi

# Show project progress (new)
if [ -f "${PROJECT_SCRIPTS}/progress.sh" ]; then
  echo ""
  echo "[recover] project progress:"
  bash "${PROJECT_SCRIPTS}/progress.sh" 2>/dev/null || true
fi

# Start background heartbeat (every 120s)
(
  while true; do
    python3 "${COORD_PY}" heartbeat "${AGENT_ID}" >/dev/null 2>&1
    sleep 120
  done
) &
HEARTBEAT_PID=$!
export HEARTBEAT_PID

echo ""
echo "[recover] heartbeat started (pid=${HEARTBEAT_PID}, interval=120s)"
echo "[recover] done — continuing work"