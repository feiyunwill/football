#!/bin/bash
# 完整工作流自动化脚本
# 用法: ./workflow.sh <action> <target_id> [options]

set -e

ACTION=$1
TARGET_ID=$2
shift 2 || true
OPTIONS="$@"

show_usage() {
  echo "用法: $0 <action> <target_id> [options]"
  echo ""
  echo "Actions:"
  echo "  complete-task <task_id> [commit_msg]    - 完成任务"
  echo "  complete-plan <plan_id>                  - 完成计划"
  echo "  complete-milestone <milestone_id>        - 完成里程碑"
  echo "  review <target_id> [review_type]         - 代码审查"
  echo "  test <target_id> [test_type]             - 运行测试"
  echo "  progress                                 - 显示进度"
  echo "  claim [agent_id]                         - 认领 milestone"
  echo ""
  echo "示例:"
  echo "  $0 complete-task task-1.1.1.1 'feat: implement UDP server'"
  echo "  $0 review plan-1.1.1 performance"
  echo "  $0 test ms-1.1 all"
}

case "$ACTION" in
  complete-task)
    if [ -z "$TARGET_ID" ]; then
      echo "错误: 请提供 task_id"
      show_usage
      exit 1
    fi
    COMMIT_MSG="${OPTIONS:-'Task completed'}"
    bash .project/scripts/task_complete.sh "$TARGET_ID" "$COMMIT_MSG"
    bash .project/scripts/auto_test.sh "$TARGET_ID" unit
    bash .project/scripts/auto_review.sh "$TARGET_ID" style
    ;;
  complete-plan)
    if [ -z "$TARGET_ID" ]; then
      echo "错误: 请提供 plan_id"
      show_usage
      exit 1
    fi
    bash .project/scripts/plan_complete.sh "$TARGET_ID"
    bash .project/scripts/auto_test.sh "$TARGET_ID" functional
    bash .project/scripts/auto_review.sh "$TARGET_ID" standard
    ;;
  complete-milestone)
    if [ -z "$TARGET_ID" ]; then
      echo "错误: 请提供 milestone_id"
      show_usage
      exit 1
    fi
    bash .project/scripts/milestone_complete.sh "$TARGET_ID"
    bash .project/scripts/auto_test.sh "$TARGET_ID" integration
    bash .project/scripts/auto_review.sh "$TARGET_ID" comprehensive
    ;;
  review)
    if [ -z "$TARGET_ID" ]; then
      echo "错误: 请提供 target_id"
      show_usage
      exit 1
    fi
    REVIEW_TYPE="${OPTIONS:-all}"
    bash .project/scripts/auto_review.sh "$TARGET_ID" "$REVIEW_TYPE"
    ;;
  test)
    if [ -z "$TARGET_ID" ]; then
      echo "错误: 请提供 target_id"
      show_usage
      exit 1
    fi
    TEST_TYPE="${OPTIONS:-all}"
    bash .project/scripts/auto_test.sh "$TARGET_ID" "$TEST_TYPE"
    ;;
  progress)
    bash .project/scripts/progress.sh
    ;;
  claim)
    AGENT_ID="${TARGET_ID:-$(hostname)-$$}"
    bash .project/scripts/auto_claim.sh "$AGENT_ID"
    ;;
  *)
    echo "错误: 未知的 action: $ACTION"
    show_usage
    exit 1
    ;;
esac
