#!/usr/bin/env bash
# auto_claim.sh — 自动认领可用的 milestone
# 用法: bash .project/scripts/auto_claim.sh <agent_id>

set -euo pipefail

AGENT_ID="${1:-}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COORD_PY="$PROJECT_ROOT/../.agent-coordination/coord.py"

if [[ -z "$AGENT_ID" ]]; then
  echo "用法: $0 <agent_id>"
  exit 1
fi

echo "[auto_claim] 检查可用 milestone..."

# 检查是否有活跃 milestone
ACTIVE=$(python3 "$COORD_PY" which-active 2>/dev/null || echo "none")
if [[ "$ACTIVE" != *"idle"* && -n "$ACTIVE" ]]; then
  echo "[auto_claim] 已有活跃 milestone，跳过认领"
  exit 0
fi

# 查找可认领的 milestone（状态为 PENDING 且无依赖或依赖已完成）
echo "[auto_claim] 查找可认领的 milestone..."

# 读取 .project 中的 milestone 文件
MILESTONES_DIR="$PROJECT_ROOT/milestones"
if [[ -d "$MILESTONES_DIR" ]]; then
  for ms_file in "$MILESTONES_DIR"/ms-*.md; do
    [[ -f "$ms_file" ]] || continue
    MS_ID=$(grep -oP '^\*\*ID\*\*: \K.*' "$ms_file" 2>/dev/null || true)
    MS_STATUS=$(grep -oP '^\*\*状态\*\*: \K.*' "$ms_file" 2>/dev/null || true)
    if [[ "$MS_STATUS" == "待开始" || "$MS_STATUS" == "PENDING" ]]; then
      echo "[auto_claim] 发现可认领 milestone: $MS_ID"
      python3 "$COORD_PY" add-milestone "$MS_ID" "从 .project/milestones 同步" 2>/dev/null || true
      python3 "$COORD_PY" claim-milestone "$MS_ID" "$AGENT_ID" 2>/dev/null || true
      echo "[auto_claim] 已认领: $MS_ID"
      exit 0
    fi
  done
fi

echo "[auto_claim] 无可用 milestone"
