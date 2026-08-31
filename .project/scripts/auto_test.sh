#!/usr/bin/env bash
# auto_test.sh — 自动运行测试
# 用法: bash .project/scripts/auto_test.sh <target_id> [test_type]

set -euo pipefail

TARGET_ID="${1:-}"
TEST_TYPE="${2:-all}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "$TARGET_ID" ]]; then
  echo "用法: $0 <target_id> [test_type]"
  echo "  test_type: all | python | cpp | e2e"
  exit 1
fi

echo "[auto_test] 运行测试: target=$TARGET_ID, type=$TEST_TYPE"

case "$TEST_TYPE" in
  python)
    echo "[auto_test] 运行 Python 测试..."
    cd "$PROJECT_ROOT/.."
    python3 -m gfootball.env.wrappers_test 2>&1 | tail -20
    ;;
  cpp)
    echo "[auto_test] 运行 C++ 测试..."
    cd "$PROJECT_ROOT/.."
    cd engine && cmake --build build_fs_asio -j 1 2>&1 | tail -10
    ;;
  e2e)
    echo "[auto_test] 运行端到端测试..."
    cd "$PROJECT_ROOT/.."
    python3 -m gfootball.frame_sync.run_e2e_test 2>&1 | tail -20
    ;;
  all)
    echo "[auto_test] 运行所有测试..."
    cd "$PROJECT_ROOT/.."
    python3 -m gfootball.env.wrappers_test 2>&1 | tail -10
    python3 -m gfootball.frame_sync.run_e2e_test 2>&1 | tail -10
    ;;
  *)
    echo "[auto_test] 未知测试类型: $TEST_TYPE"
    exit 1
    ;;
esac

echo "[auto_test] 测试完成"
