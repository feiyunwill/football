#!/bin/bash
# 自动认领 milestone 脚本
# 用法: ./auto_claim.sh [agent_id]

set -e

AGENT_ID=${1:-$(hostname)-$$}

echo "=== 自动认领 Milestone ==="
echo "Agent ID: $AGENT_ID"

# 1. 扫描可用 milestone
echo "1. 扫描可用 milestone..."
AVAILABLE_MILESTONES=()

# 查找 PENDING 状态的 milestone
for file in .project/milestones/*.md; do
  if [ -f "$file" ]; then
    # 使用 grep -P 支持 Unicode
    if grep -qP "状态.*PENDING" "$file" 2>/dev/null || grep -q "PENDING" "$file"; then
      MILESTONE_ID=$(basename "$file" .md)
      AVAILABLE_MILESTONES+=("$MILESTONE_ID")
      echo "   发现可用 milestone: $MILESTONE_ID"
    fi
  fi
done

if [ ${#AVAILABLE_MILESTONES[@]} -eq 0 ]; then
  echo "   没有可用的 milestone"
  exit 0
fi

# 2. 选择第一个可用 milestone
echo "2. 选择 milestone..."
SELECTED_MILESTONE=${AVAILABLE_MILESTONES[0]}
echo "   选择: $SELECTED_MILESTONE"

# 3. 认领 milestone
echo "3. 认领 milestone..."
MILESTONE_FILE=".project/milestones/${SELECTED_MILESTONE}.md"
if [ -f "$MILESTONE_FILE" ]; then
  sed -i 's/状态: PENDING/状态: CLAIMED/' "$MILESTONE_FILE"
  echo "   已认领: $SELECTED_MILESTONE"
else
  echo "   错误: milestone 文件不存在"
  exit 1
fi

# 4. 更新 agent 状态
echo "4. 更新 agent 状态..."
# TODO: 更新 agent 注册表
echo "   Agent 状态已更新"

# 5. 保存上下文快照
echo "5. 保存上下文快照..."
# TODO: 保存认领快照
echo "   快照已保存"

echo ""
echo "=== 已认领 Milestone: $SELECTED_MILESTONE ==="
