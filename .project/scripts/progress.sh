#!/usr/bin/env bash
# progress.sh — 显示项目进度
# 用法: bash .project/scripts/progress.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COORD_PY="$PROJECT_ROOT/../.agent-coordination/coord.py"

echo "========================================="
echo "  项目进度报告"
echo "========================================="
echo ""

# Agent 状态
echo "【Agent 状态】"
python3 "$COORD_PY" agents 2>/dev/null || echo "  无注册 agent"
echo ""

# 活跃 milestone
echo "【活跃 Milestone】"
python3 "$COORD_PY" which-active 2>/dev/null || echo "  无活跃 milestone"
echo ""

# 所有 milestone
echo "【Milestone 列表】"
python3 "$COORD_PY" list-milestones 2>/dev/null || echo "  无 milestone"
echo ""

# .project 中的 milestone 统计
echo "【.project Milestone 统计】"
MILESTONES_DIR="$PROJECT_ROOT/milestones"
if [[ -d "$MILESTONES_DIR" ]]; then
  TOTAL=$(ls "$MILESTONES_DIR"/ms-*.md 2>/dev/null | wc -l || echo 0)
  COMPLETED=$(grep -l "状态.*COMPLETED\|状态.*已完成" "$MILESTONES_DIR"/ms-*.md 2>/dev/null | wc -l || echo 0)
  PENDING=$((TOTAL - COMPLETED))
  echo "  总计: $TOTAL | 已完成: $COMPLETED | 待开始: $PENDING"
else
  echo "  无 milestone 文件"
fi
echo ""

# Git 状态
echo "【Git 状态】"
echo "  最近提交:"
git log --oneline -5 2>/dev/null | sed 's/^/    /'
echo ""
echo "  分支:"
git branch 2>/dev/null | sed 's/^/    /'
echo ""

echo "========================================="
