#!/bin/bash
# ECS 性能测试脚本
# 2026-09-02 Phase 9: 性能测试验证

set -e

ENGINE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ENGINE_DIR"

export CC=/opt/rh/gcc-toolset-15/root/usr/bin/gcc
export CXX=/opt/rh/gcc-toolset-15/root/usr/bin/g++

echo "=========================================="
echo "ECS Performance Test Suite"
echo "=========================================="
echo ""

# 1. Code Metrics
echo "1. Code Metrics"
echo "----------------"
echo "ECS Files: $(find src/ecs -name '*.hpp' -o -name '*.cpp' | wc -l)"
echo "ECS Lines of Code: $(find src/ecs -name '*.hpp' -o -name '*.cpp' -exec cat {} \; | wc -l)"
echo "OnThePitch Files: $(find src/onthepitch -name '*.hpp' -o -name '*.cpp' | wc -l)"
echo "OnThePitch Lines of Code: $(find src/onthepitch -name '*.hpp' -o -name '*.cpp' -exec cat {} \; | wc -l)"
echo ""

# 2. Compile Time Tests
echo "2. Compile Time Tests"
echo "---------------------"
echo "Testing ecs_direct_systems.cpp..."
time $CXX -std=c++23 -fsyntax-only -I src -I src/cmake -I src/base -I src/ecs -I src/onthepitch -I src/onthepitch/player -I src/onthepitch/player/humanoid src/onthepitch/ecs_direct_systems.cpp 2>&1

echo "Testing system_batch.cpp..."
time $CXX -std=c++23 -fsyntax-only -I src -I src/cmake -I src/base -I src/ecs -I src/onthepitch -I src/onthepitch/player -I src/onthepitch/player/humanoid src/ecs/system_batch.cpp 2>&1

echo "Testing match.cpp..."
time $CXX -std=c++23 -fsyntax-only -I src -I src/cmake -I src/base -I src/ecs -I src/onthepitch -I src/onthepitch/player -I src/onthepitch/player/humanoid src/onthepitch/match.cpp 2>&1

echo ""

# 3. Code Complexity Analysis
echo "3. Code Complexity Analysis"
echo "---------------------------"
echo "Function count in ecs_direct_systems.cpp:"
grep -c "void.*System" src/onthepitch/ecs_direct_systems.cpp || echo "0"

echo "Function count in system_batch.cpp:"
grep -c "void.*Execute" src/ecs/system_batch.cpp || echo "0"

echo "Template usage in query.hpp:"
grep -c "template" src/ecs/query.hpp || echo "0"

echo ""

# 4. Memory Usage Estimation
echo "4. Memory Usage Estimation"
echo "--------------------------"
echo "Component struct sizes (approximate):"
echo "PlayerStateComponent: $(grep -A 50 "struct PlayerStateComponent" src/onthepitch/ecs_components.hpp | grep -c "int\|float\|Vector3\|bool") fields"
echo "HumanoidStateComponent: $(grep -A 50 "struct HumanoidStateComponent" src/onthepitch/ecs_components.hpp | grep -c "int\|float\|Vector3\|bool\|e_FunctionType") fields"
echo "OfficialsComponent: $(grep -A 20 "struct OfficialsComponent" src/onthepitch/ecs_components.hpp | grep -c "int\|float\|Vector3\|bool") fields"
echo ""

echo "=========================================="
echo "Performance Test Complete"
echo "=========================================="
