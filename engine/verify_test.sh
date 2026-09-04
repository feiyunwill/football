#!/bin/bash
# ECS 功能完整性验证测试脚本
# 2026-09-02 Phase 9: 功能完整性验证

set -e

ENGINE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ENGINE_DIR"

export CC=/opt/rh/gcc-toolset-15/root/usr/bin/gcc
export CXX=/opt/rh/gcc-toolset-15/root/usr/bin/g++

echo "=========================================="
echo "ECS Functional Verification Test Suite"
echo "=========================================="
echo ""

PASS_COUNT=0
FAIL_COUNT=0

# Test function
run_test() {
    local test_name="$1"
    local test_cmd="$2"
    
    echo "Running: $test_name"
    if eval "$test_cmd" 2>&1; then
        echo "  PASS"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "  FAIL"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
    echo ""
}

# 1. Syntax Check Tests
echo "1. Syntax Check Tests"
echo "---------------------"

run_test "ecs_direct_systems.cpp syntax" \
    "$CXX -std=c++23 -fsyntax-only -I src -I src/cmake -I src/base -I src/ecs -I src/onthepitch -I src/onthepitch/player -I src/onthepitch/player/humanoid src/onthepitch/ecs_direct_systems.cpp"

run_test "system_batch.cpp syntax" \
    "$CXX -std=c++23 -fsyntax-only -I src -I src/cmake -I src/base -I src/ecs -I src/onthepitch -I src/onthepitch/player -I src/onthepitch/player/humanoid src/ecs/system_batch.cpp"

run_test "match.cpp syntax" \
    "$CXX -std=c++23 -fsyntax-only -I src -I src/cmake -I src/base -I src/ecs -I src/onthepitch -I src/onthepitch/player -I src/onthepitch/player/humanoid src/onthepitch/match.cpp"

run_test "query.hpp syntax" \
    "$CXX -std=c++23 -fsyntax-only -I src -I src/cmake -I src/base -I src/ecs src/ecs/query.hpp"

run_test "system_batch.hpp syntax" \
    "$CXX -std=c++23 -fsyntax-only -I src -I src/cmake -I src/base -I src/ecs src/ecs/system_batch.hpp"

# 2. Component Structure Tests
echo "2. Component Structure Tests"
echo "----------------------------"

run_test "PlayerStateComponent exists" \
    "grep -q 'struct PlayerStateComponent' src/onthepitch/ecs_components.hpp"

run_test "HumanoidStateComponent exists" \
    "grep -q 'struct HumanoidStateComponent' src/onthepitch/ecs_components.hpp"

run_test "OfficialsComponent exists" \
    "grep -q 'struct OfficialsComponent' src/onthepitch/ecs_components.hpp"

# 3. System Function Tests
echo "3. System Function Tests"
echo "------------------------"

run_test "PlayerStateSystemDirect exists" \
    "grep -q 'void PlayerStateSystemDirect' src/onthepitch/ecs_direct_systems.cpp"

run_test "HumanoidStateSystemDirect exists" \
    "grep -q 'void HumanoidStateSystemDirect' src/onthepitch/ecs_direct_systems.cpp"

run_test "OfficialsSystemDirect exists" \
    "grep -q 'void OfficialsSystemDirect' src/onthepitch/ecs_direct_systems.cpp"

# 4. Batch System Tests
echo "4. Batch System Tests"
echo "---------------------"

run_test "PlayerSystemBatch exists" \
    "grep -q 'class PlayerSystemBatch' src/ecs/system_batch.hpp"

run_test "OfficialsSystemBatch exists" \
    "grep -q 'class OfficialsSystemBatch' src/ecs/system_batch.hpp"

run_test "PossessionStatsBatch exists" \
    "grep -q 'class PossessionStatsBatch' src/ecs/system_batch.hpp"

# 5. Query Interface Tests
echo "5. Query Interface Tests"
echo "------------------------"

run_test "QueryResult exists" \
    "grep -q 'class QueryResult' src/ecs/query.hpp"

run_test "QueryBuilder exists" \
    "grep -q 'class QueryBuilder' src/ecs/query.hpp"

run_test "Query function exists" \
    "grep -q 'QueryBuilder.*Query' src/ecs/query.hpp"

# Summary
echo "=========================================="
echo "Verification Complete"
echo "=========================================="
echo "Passed: $PASS_COUNT"
echo "Failed: $FAIL_COUNT"
echo ""

if [ $FAIL_COUNT -eq 0 ]; then
    echo "All tests passed!"
    exit 0
else
    echo "Some tests failed!"
    exit 1
fi
