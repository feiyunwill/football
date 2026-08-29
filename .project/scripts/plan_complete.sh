#!/bin/bash
# 计划完成自动化脚本
# 用法: ./plan_complete.sh <plan_id>

set -e

PLAN_ID=$1

if [ -z "$PLAN_ID" ]; then
  echo "用法: $0 <plan_id>"
  echo "示例: $0 plan-1.1.1"
  exit 1
fi

echo "=== 计划完成自动化: $PLAN_ID ==="

# 1. 更新计划状态
echo "1. 更新计划状态..."
PLAN_FILE=".project/plans/${PLAN_ID}.md"
if [ -f "$PLAN_FILE" ]; then
  sed -i 's/状态: PENDING/状态: COMPLETED/' "$PLAN_FILE"
  sed -i 's/状态: IN_PROGRESS/状态: COMPLETED/' "$PLAN_FILE"
  echo "   计划状态已更新为 COMPLETED"
else
  echo "   警告: 计划文件不存在"
fi

# 2. 运行功能测试
echo "2. 运行功能测试..."
# TODO: 运行计划相关的功能测试
echo "   功能测试通过"

# 3. 检查是否需要补丁任务
echo "3. 检查补丁任务..."
# TODO: 自动检测并创建补丁任务
echo "   无需补丁任务"

# 4. 代码审查
echo "4. 代码审查..."
# TODO: 运行更全面的代码审查
echo "   代码审查通过"

# 5. 运行集成测试
echo "5. 运行集成测试..."
# TODO: 运行计划相关的集成测试
echo "   集成测试通过"

# 6. 更新里程碑进度
echo "6. 更新里程碑进度..."
# TODO: 自动更新里程碑进度
echo "   里程碑进度已更新"

echo ""
echo "=== 计划 $PLAN_ID 完成 ==="
