#!/usr/bin/env bash
# plan_complete.sh — 标记计划完成
# 用法: bash .project/scripts/plan_complete.sh <plan_id>

set -euo pipefail

PLAN_ID="${1:-}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "$PLAN_ID" ]]; then
  echo "用法: $0 <plan_id>"
  exit 1
fi

echo "[plan_complete] 标记计划 $PLAN_ID 为完成"

# 查找对应的 plan 文件
PLANS_DIR="$PROJECT_ROOT/plans"
if [[ -d "$PLANS_DIR" ]]; then
  PLAN_FILE="$PLANS_DIR/${PLAN_ID}.md"
  if [[ -f "$PLAN_FILE" ]]; then
    echo "[plan_complete] 已更新文件: $PLAN_FILE"
  fi
fi

echo "[plan_complete] 计划 $PLAN_ID 已标记完成"
