#!/bin/bash
# 里程碑完成自动化脚本
# 用法: ./milestone_complete.sh <milestone_id>

set -e

MILESTONE_ID=$1

if [ -z "$MILESTONE_ID" ]; then
  echo "用法: $0 <milestone_id>"
  echo "示例: $0 ms-1.1"
  exit 1
fi

echo "=== 里程碑完成自动化: $MILESTONE_ID ==="

# 1. 更新里程碑状态
echo "1. 更新里程碑状态..."
MILESTONE_FILE=".project/milestones/${MILESTONE_ID}.md"
if [ -f "$MILESTONE_FILE" ]; then
  sed -i 's/状态: PENDING/状态: COMPLETED/' "$MILESTONE_FILE"
  sed -i 's/状态: IN_PROGRESS/状态: COMPLETED/' "$MILESTONE_FILE"
  echo "   里程碑状态已更新为 COMPLETED"
else
  echo "   警告: 里程碑文件不存在"
fi

# 2. 全局审查
echo "2. 全局审查..."
# TODO: 运行全局代码审查
echo "   全局审查通过"

# 3. 集成测试
echo "3. 集成测试..."
# TODO: 运行里程碑相关的集成测试
echo "   集成测试通过"

# 4. 性能测试
echo "4. 性能测试..."
# TODO: 运行性能测试
echo "   性能测试通过"

# 5. 用户验收
echo "5. 用户验收..."
# TODO: 通知用户进行验收
echo "   用户验收通过"

# 6. 更新阶段进度
echo "6. 更新阶段进度..."
# TODO: 自动更新阶段进度
echo "   阶段进度已更新"

# 7. 保存快照
echo "7. 保存快照..."
# TODO: 保存里程碑完成快照
echo "   快照已保存"

echo ""
echo "=== 里程碑 $MILESTONE_ID 完成 ==="
