#!/usr/bin/env bash
# auto_review.sh — 自动代码审查
# 用法: bash .project/scripts/auto_review.sh <target_id> [review_type]

set -euo pipefail

TARGET_ID="${1:-}"
REVIEW_TYPE="${2:-full}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "$TARGET_ID" ]]; then
  echo "用法: $0 <target_id> [review_type]"
  echo "  review_type: full | quick | security"
  exit 1
fi

echo "[auto_review] 代码审查: target=$TARGET_ID, type=$REVIEW_TYPE"

# 检查最近的提交
echo "[auto_review] 检查最近提交..."
git log --oneline -5 2>/dev/null | sed 's/^/    /'

# 检查修改的文件
echo "[auto_review] 检查修改的文件..."
git diff --name-only HEAD~1 2>/dev/null | sed 's/^/    /'

# 检查是否有 TODO/FIXME
echo "[auto_review] 检查 TODO/FIXME..."
git diff --name-only HEAD~1 2>/dev/null | while read -r file; do
  if [[ -f "$PROJECT_ROOT/$file" ]]; then
    grep -n "TODO\|FIXME\|HACK\|XXX" "$PROJECT_ROOT/$file" 2>/dev/null | sed "s/^/    $file: /"
  fi
done

echo "[auto_review] 代码审查完成"
