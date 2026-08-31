#!/usr/bin/env bash
# workflow.sh — 主工作流脚本
# 用法: bash .project/scripts/workflow.sh <action> <target_id> [options]

set -euo pipefail

ACTION="${1:-}"
TARGET_ID="${2:-}"
OPTIONS="${3:-}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "$ACTION" || -z "$TARGET_ID" ]]; then
  echo "用法: $0 <action> <target_id> [options]"
  echo ""
  echo "Actions:"
  echo "  claim       认领 milestone"
  echo "  start       开始 milestone"
  echo "  complete    完成 milestone/task"
  echo "  fail        标记失败"
  echo "  progress    记录进展"
  echo "  snapshot    保存快照"
  echo "  test        运行测试"
  echo "  review      代码审查"
  echo ""
  exit 1
fi

case "$ACTION" in
  claim)
    bash "$PROJECT_ROOT/scripts/auto_claim.sh" "$TARGET_ID"
    ;;
  start)
    echo "[workflow] 开始 milestone: $TARGET_ID"
    COORD_PY="$PROJECT_ROOT/../.agent-coordination/coord.py"
    python3 "$COORD_PY" start-milestone "$TARGET_ID" "$OPTIONS" 2>/dev/null || true
    ;;
  complete)
    if [[ "$TARGET_ID" == ms-* ]]; then
      bash "$PROJECT_ROOT/scripts/milestone_complete.sh" "$TARGET_ID"
    else
      bash "$PROJECT_ROOT/scripts/task_complete.sh" "$TARGET_ID" "$OPTIONS"
    fi
    ;;
  fail)
    echo "[workflow] 标记失败: $TARGET_ID"
    COORD_PY="$PROJECT_ROOT/../.agent-coordination/coord.py"
    python3 "$COORD_PY" fail-milestone "$TARGET_ID" "$OPTIONS" 2>/dev/null || true
    ;;
  progress)
    echo "[workflow] 记录进展: $TARGET_ID"
    COORD_PY="$PROJECT_ROOT/../.agent-coordination/coord.py"
    python3 "$COORD_PY" add-progress "$TARGET_ID" "$OPTIONS" 2>/dev/null || true
    ;;
  snapshot)
    echo "[workflow] 保存快照: $TARGET_ID"
    COORD_PY="$PROJECT_ROOT/../.agent-coordination/coord.py"
    python3 "$COORD_PY" snapshot "$TARGET_ID" "$OPTIONS" 2>/dev/null || true
    ;;
  test)
    bash "$PROJECT_ROOT/scripts/auto_test.sh" "$TARGET_ID" "$OPTIONS"
    ;;
  review)
    bash "$PROJECT_ROOT/scripts/auto_review.sh" "$TARGET_ID" "$OPTIONS"
    ;;
  *)
    echo "[workflow] 未知操作: $ACTION"
    exit 1
    ;;
esac
