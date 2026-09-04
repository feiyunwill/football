#!/bin/bash
# Phase 10 功能完整性验证测试脚本
# 2026-09-02 Phase 10: 功能完整性验证

set -e

ENGINE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ENGINE_DIR"

export CC=/opt/rh/gcc-toolset-15/root/usr/bin/gcc
export CXX=/opt/rh/gcc-toolset-15/root/usr/bin/g++

echo "=========================================="
echo "Phase 10 Functional Verification Test Suite"
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

# 2. Component Structure Tests
echo "2. Component Structure Tests"
echo "----------------------------"

run_test "TeamStateComponent exists" \
    "grep -q 'struct TeamStateComponent' src/onthepitch/ecs_components.hpp"

run_test "RefereeStateComponent exists" \
    "grep -q 'struct RefereeStateComponent' src/onthepitch/ecs_components.hpp"

run_test "MentalImageComponent exists" \
    "grep -q 'struct MentalImageComponent' src/onthepitch/ecs_components.hpp"

# 3. System Function Tests
echo "3. System Function Tests"
echo "------------------------"

run_test "TeamProcessSystemDirect exists" \
    "grep -q 'void TeamProcessSystemDirect' src/onthepitch/ecs_direct_systems.cpp"

run_test "RefereeProcessSystemDirect exists" \
    "grep -q 'void RefereeProcessSystemDirect' src/onthepitch/ecs_direct_systems.cpp"

run_test "MentalImageSyncSystemDirect exists" \
    "grep -q 'void MentalImageSyncSystemDirect' src/onthepitch/ecs_direct_systems.cpp"

# 4. Batch System Tests
echo "4. Batch System Tests"
echo "---------------------"

run_test "TeamSystemBatch exists" \
    "grep -q 'class TeamSystemBatch' src/ecs/system_batch.hpp"

run_test "RefereeSystemBatch exists" \
    "grep -q 'class RefereeSystemBatch' src/ecs/system_batch.hpp"

run_test "MentalImageSystemBatch exists" \
    "grep -q 'class MentalImageSystemBatch' src/ecs/system_batch.hpp"

run_test "GameLogicBatch exists" \
    "grep -q 'class GameLogicBatch' src/ecs/system_batch.hpp"

# 5. Match Method Tests
echo "5. Match Method Tests"
echo "---------------------"

run_test "GetEcsRefereeEntity exists" \
    "grep -q 'GetEcsRefereeEntity' src/onthepitch/match.hpp"

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
