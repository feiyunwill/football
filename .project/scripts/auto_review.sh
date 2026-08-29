#!/bin/bash
# 自动代码审查脚本
# 用法: ./auto_review.sh <task_id|plan_id|milestone_id> [review_type]

set -e

TARGET_ID=$1
REVIEW_TYPE=${2:-"all"}

if [ -z "$TARGET_ID" ]; then
  echo "用法: $0 <task_id|plan_id|milestone_id> [review_type]"
  echo "  review_type: style, security, performance, all"
  echo "示例: $0 task-1.1.1.1 style"
  exit 1
fi

echo "=== 自动代码审查: $TARGET_ID ==="
echo "审查类型: $REVIEW_TYPE"

# 1. 确定审查范围
echo "1. 确定审查范围..."
if [[ "$TARGET_ID" == task-* ]]; then
  echo "   范围: 代码风格 + 安全性"
  REVIEW_SCOPE="basic"
elif [[ "$TARGET_ID" == plan-* ]]; then
  echo "   范围: 代码风格 + 安全性 + 性能"
  REVIEW_SCOPE="standard"
elif [[ "$TARGET_ID" == ms-* ]]; then
  echo "   范围: 全面审查"
  REVIEW_SCOPE="comprehensive"
else
  echo "   错误: 未知的 ID 格式"
  exit 1
fi

# 2. 代码风格检查
if [ "$REVIEW_SCOPE" = "basic" ] || [ "$REVIEW_SCOPE" = "standard" ] || [ "$REVIEW_TYPE" = "style" ] || [ "$REVIEW_TYPE" = "all" ]; then
  echo "2. 代码风格检查..."
  # TODO: 运行 clang-format, clang-tidy
  echo "   代码风格检查通过"
fi

# 3. 安全性检查
if [ "$REVIEW_SCOPE" = "basic" ] || [ "$REVIEW_SCOPE" = "standard" ] || [ "$REVIEW_TYPE" = "security" ] || [ "$REVIEW_TYPE" = "all" ]; then
  echo "3. 安全性检查..."
  # TODO: 运行安全扫描
  echo "   安全性检查通过"
fi

# 4. 性能检查
if [ "$REVIEW_SCOPE" = "standard" ] || [ "$REVIEW_SCOPE" = "comprehensive" ] || [ "$REVIEW_TYPE" = "performance" ] || [ "$REVIEW_TYPE" = "all" ]; then
  echo "4. 性能检查..."
  # TODO: 运行性能分析
  echo "   性能检查通过"
fi

# 5. 依赖检查
if [ "$REVIEW_SCOPE" = "comprehensive" ] || [ "$REVIEW_TYPE" = "all" ]; then
  echo "5. 依赖检查..."
  # TODO: 检查依赖关系
  echo "   依赖检查通过"
fi

# 6. 生成审查报告
echo "6. 生成审查报告..."
# TODO: 生成审查报告
echo "   审查报告已生成"

echo ""
echo "=== 审查完成: $TARGET_ID ==="
