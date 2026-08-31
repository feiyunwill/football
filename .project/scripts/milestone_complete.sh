#!/usr/bin/env bash
# milestone_complete.sh — 标记 milestone 完成
# 用法: bash .project/scripts/milestone_complete.sh <milestone_id>

set -euo pipefail

MS_ID="${1:-}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COORD_PY="$PROJECT_ROOT/../.agent-coordination/coord.py"

if [[ -z "$MS_ID" ]]; then
  echo "用法: $0 <milestone_id>"
  exit 1
fi

echo "[milestone_complete] 标记 milestone $MS_ID 为完成"

# 查找对应的 milestone 文件
MILESTONES_DIR="$PROJECT_ROOT/milestones"
MS_FILE="$MILESTONES_DIR/${MS_ID}.md"

if [[ -f "$MS_FILE" ]]; then
  # 更新状态为 COMPLETED
  sed -i 's/状态.*: 待开始/状态: COMPLETED/' "$MS_FILE"
  sed -i 's/状态.*: PENDING/状态: COMPLETED/' "$MS_FILE"
  echo "[milestone_complete] 已更新文件: $MS_FILE"
fi

# 更新 coord.py 中的状态
python3 "$COORD_PY" complete-milestone "$MS_ID" "auto" 2>/dev/null || true

echo "[milestone_complete] Milestone $MS_ID 已标记完成"
