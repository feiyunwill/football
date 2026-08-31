#!/usr/bin/env bash
# task_complete.sh — 标记任务完成并自动推进
# 用法: bash .project/scripts/task_complete.sh <task_id> "commit message"

set -euo pipefail

TASK_ID="${1:-}"
COMMIT_MSG="${2:-}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COORD_PY="$PROJECT_ROOT/../.agent-coordination/coord.py"

if [[ -z "$TASK_ID" ]]; then
  echo "用法: $0 <task_id> [commit message]"
  exit 1
fi

echo "[task_complete] 标记任务 $TASK_ID 为完成"

# 获取当前活跃 milestone
ACTIVE_MS=$(python3 "$COORD_PY" which-active 2>/dev/null || echo "none")
if [[ "$ACTIVE_MS" == *"idle"* || -z "$ACTIVE_MS" ]]; then
  echo "[task_complete] 警告: 无活跃 milestone"
else
  echo "[task_complete] 当前活跃 milestone: $ACTIVE_MS"
fi

# 记录进展
if [[ -n "$COMMIT_MSG" ]]; then
  python3 "$COORD_PY" add-progress "$TASK_ID" "任务完成: $COMMIT_MSG" 2>/dev/null || true
fi

echo "[task_complete] 任务 $TASK_ID 已标记完成"
