# C++ 单元测试（gtest），通过 FetchContent 自动下载 GoogleTest。
# 构建：cmake -S tests -B build_tests && cmake --build build_tests -j 1
# 运行：./build_tests/frame_sync_test
# 2026-09-01 优化：统一目标定义、预编译头、Unity 构建

cmake_minimum_required(VERSION 3.14)
project(gfootball_tests CXX)

# 2026-09-09: make discovered tests visible to CTest and separate timing gates.
enable_testing()
option(ENABLE_PERFORMANCE_TESTS "Run machine-dependent timing benchmarks" OFF)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ===== 构建优化 =====
# Unity 构建（减少编译时间 30-50%）
option(CMAKE_UNITY_BUILD "Enable Unity builds" ON)
# 2026-09-09: INT is not a CMake cache type.
# set(CMAKE_UNITY_BUILD_BATCH_SIZE 8 CACHE INT "Unity build batch size")
set(CMAKE_UNITY_BUILD_BATCH_SIZE 8 CACHE STRING "Unity build batch size")

# 预编译头（减少重复编译）
option(ENABLE_PCH "Enable precompiled headers" ON)

# 2026-09-15: reuse an installed compatible test package before the pinned source fallback.
# Previous unconditional download:
# # FetchContent 自动下载 GoogleTest
# include(FetchContent)
# FetchContent_Declare(
#   googletest
#   GIT_REPOSITORY https://github.com/google/googletest.git
#   GIT_TAG v1.14.0
# )
# # Prevent GoogleTest from overriding our compiler/linker options
# set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
# FetchContent_MakeAvailable(googletest)
find_package(GTest 1.14 CONFIG QUIET)
if(GTest_FOUND)
  set(FOOTBALL_GTEST_MAIN_TARGET GTest::gtest_main)
  message(STATUS "Using installed GoogleTest ${GTest_VERSION} at ${GTest_DIR}")
else()
  # FetchContent 自动下载 GoogleTest
  include(FetchContent)
  FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.14.0
  )
  # Prevent GoogleTest from overriding our compiler/linker options
  set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)
  set(FOOTBALL_GTEST_MAIN_TARGET gtest_main)
endif()

include(GoogleTest)

# ===== Sanitizer 选项 =====
# 用法：cmake -S tests -B build_tests -DENABLE_ASAN=ON
option(ENABLE_ASAN "Enable AddressSanitizer" OFF)
option(ENABLE_UBSAN "Enable UndefinedBehaviorSanitizer" OFF)
option(ENABLE_TSAN "Enable ThreadSanitizer" OFF)

if(ENABLE_ASAN)
  # 2026-08-28 已安装 gcc-toolset-15-libasan-devel
  add_compile_options(-fsanitize=address -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address)
  message(STATUS "AddressSanitizer enabled")
endif()
if(ENABLE_UBSAN)
  add_compile_options(-fsanitize=undefined -fno-omit-frame-pointer)
  add_link_options(-fsanitize=undefined)
  message(STATUS "UndefinedBehaviorSanitizer enabled")
endif()
if(ENABLE_TSAN)
  add_compile_options(-fsanitize=thread -fno-omit-frame-pointer)
  add_link_options(-fsanitize=thread)
  message(STATUS "ThreadSanitizer enabled")
endif()

# ===== 优化编译选项 =====
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Release 模式优化
if(CMAKE_BUILD_TYPE STREQUAL "Release")
  add_compile_options(-O3 -DNDEBUG)
endif()

# ===== 引擎源码目录 =====
set(ENGINE_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../src")

# ===== 公共目标属性 =====
# 所有测试目标共享的 include 目录和链接库
function(configure_test_target target)
  target_include_directories(${target} PRIVATE ${ENGINE_SRC})
  # 2026-09-15: both installed and fetched packages select the same main-test API.
  # target_link_libraries(${target} PRIVATE gtest_main)
  target_link_libraries(${target} PRIVATE ${FOOTBALL_GTEST_MAIN_TARGET})
  target_compile_definitions(${target} PRIVATE FRAME_SYNC_TIMING_CHECKS=$<BOOL:${ENABLE_PERFORMANCE_TESTS}>)
  
  # 预编译头（可选）
  if(ENABLE_PCH)
    target_precompile_headers(${target} PRIVATE
      <gtest/gtest.h>
      <vector>
      <string>
      <cstdint>
      <cstring>
    )
  endif()
endfunction()

# ===== 测试目标定义 =====
# 使用宏简化目标定义
macro(add_frame_sync_test name source)
  add_executable(${name} ${source})
  configure_test_target(${name})
  # 2026-09-09: performance assertions belong to an optimized benchmark run.
  # gtest_discover_tests(${name})
  if(ENABLE_PERFORMANCE_TESTS)
    gtest_discover_tests(${name} PROPERTIES TIMEOUT 30)
  else()
    gtest_discover_tests(${name} TEST_FILTER "-PerformanceTest.*" PROPERTIES TIMEOUT 30)
  endif()
endmacro()

# 帧同步协议测试
add_frame_sync_test(frame_sync_test frame_sync_test.cpp)

# ECS 组件测试
add_frame_sync_test(ecs_test ecs_test.cpp)
add_frame_sync_test(ecs_query_contract_test ecs_query_contract_test.cpp)

# FixedPoint 定点数测试
add_frame_sync_test(fixed_point_test fixed_point_test.cpp)

# FixedPoint 跨平台确定性测试
add_frame_sync_test(fixed_point_determinism_test fixed_point_determinism_test.cpp)

# ClientState 预测/回滚测试
add_frame_sync_test(client_state_test client_state_test.cpp)

# PlayerPhysicsComponent 测试
add_frame_sync_test(ecs_physics_sync_test ecs_physics_sync_test.cpp)

# ECS 性能基准测试
add_frame_sync_test(ecs_benchmark_test ecs_benchmark_test.cpp)

# 引擎集成测试
add_frame_sync_test(engine_integration_test engine_integration_test.cpp)

# Phase 5 商业级优化测试
add_frame_sync_test(phase5_test phase5_test.cpp)

# 性能基准测试
add_frame_sync_test(performance_benchmark_test performance_benchmark_test.cpp)

# 帧同步性能优化测试
# 2026-09-09: this executable has its own main and contains no GoogleTests.
# add_frame_sync_test(frame_sync_performance_test frame_sync_performance_test.cpp)
add_executable(frame_sync_performance_test frame_sync_performance_test.cpp)
target_include_directories(frame_sync_performance_test PRIVATE ${ENGINE_SRC})
if(ENABLE_PERFORMANCE_TESTS)
  add_test(NAME frame_sync_performance COMMAND frame_sync_performance_test)
  set_tests_properties(frame_sync_performance PROPERTIES TIMEOUT 30 LABELS performance)
endif()

# UX 优化测试
add_frame_sync_test(ux_optimizer_test ux_optimizer_test.cpp)

# 帧同步覆盖测试
add_frame_sync_test(frame_sync_coverage_test frame_sync_coverage_test.cpp)

# 确定性 PRNG 测试 (ms-16.2)
add_frame_sync_test(prng_test prng_test.cpp)

# 插值/外推测试 (ms-16.3)
add_frame_sync_test(interpolator_test interpolator_test.cpp)

# 状态 Delta 压缩测试 (ms-16.4)
add_frame_sync_test(state_delta_codec_test state_delta_codec_test.cpp)

# 预测准确率追踪测试 (ms-16.5)
add_frame_sync_test(prediction_accuracy_tracker_test prediction_accuracy_tracker_test.cpp)

# 自适应预测上限测试 (ms-16.6)
add_frame_sync_test(adaptive_prediction_cap_test adaptive_prediction_cap_test.cpp)

# 回放系统测试 (ms-16.7)
add_frame_sync_test(replay_system_test replay_system_test.cpp)

# 自适应抖动缓冲测试 (ms-16.8)
add_frame_sync_test(adaptive_jitter_buffer_test adaptive_jitter_buffer_test.cpp)

# Phase 16 集成测试 (ms-16.9)
add_frame_sync_test(phase16_integration_test phase16_integration_test.cpp)

# 延迟补偿测试 (ms-17.1)
add_frame_sync_test(latency_compensator_test latency_compensator_test.cpp)

# 状态快照压缩测试 (ms-17.2)
add_frame_sync_test(state_snapshot_codec_test state_snapshot_codec_test.cpp)

# 观战模式测试 (ms-17.3)
add_frame_sync_test(spectator_test spectator_test.cpp)

# 回放系统集成测试 (ms-17.4)
add_frame_sync_test(replay_integration_test replay_integration_test.cpp)

# 网络诊断工具测试 (ms-17.5)
add_frame_sync_test(network_diagnostics_test network_diagnostics_test.cpp)

# 大厅协议测试 (ms-18.1)
add_frame_sync_test(lobby_protocol_test lobby_protocol_test.cpp)

# 房间管理器测试 (ms-18.2)
add_frame_sync_test(room_manager_test room_manager_test.cpp)

# 大厅端到端测试 (ms-18.5)
add_frame_sync_test(lobby_e2e_test lobby_e2e_test.cpp)

add_frame_sync_test(milestone_regression_test milestone_regression_test.cpp)
add_frame_sync_test(frame_simulation_test frame_simulation_test.cpp)
add_frame_sync_test(memory_budget_test memory_budget_test.cpp)
# 2026-09-10: native Linux filesystem publication and maximum replay contract.
add_frame_sync_test(replay_file_test replay_file_test.cpp)
# 2026-09-13: actual filesystem quotas, processes and crash recovery.
add_frame_sync_test(replay_directory_test replay_directory_test.cpp)
add_frame_sync_test(reliable_udp_budget_test reliable_udp_budget_test.cpp)
add_frame_sync_test(bounded_tcp_writer_test bounded_tcp_writer_test.cpp)
add_frame_sync_test(lobby_capacity_test lobby_capacity_test.cpp)
add_frame_sync_test(lobby_client_capacity_test lobby_client_capacity_test.cpp)
add_frame_sync_test(tcp_frame_server_test tcp_frame_server_test.cpp)
add_frame_sync_test(tcp_client_capacity_test tcp_client_capacity_test.cpp)


# 2026-09-24: permanent native UDP contracts, including real loopback and ownership.
# The supported acceptance target is Linux x86_64; fixtures use poll().
if(UNIX)
  find_package(OpenSSL 3.0 REQUIRED COMPONENTS Crypto)
  find_package(Threads REQUIRED)
  add_library(football_test_native_recovery STATIC ../src/frame_sync/native_recovery_digest.cpp)
  target_include_directories(football_test_native_recovery PUBLIC ${ENGINE_SRC})
  target_link_libraries(football_test_native_recovery PUBLIC OpenSSL::Crypto)
  foreach(target native_udp_bootstrap_test native_udp_window_test native_udp_stream_test native_udp_listener_test native_udp_dialer_test native_udp_terminal_drain_test)
    add_executable(${target} ${target}.cpp)
    configure_test_target(${target})
    target_link_libraries(${target} PRIVATE football_test_native_recovery Threads::Threads)
    # Prefixes keep inherited legacy witnesses distinct from their original target.
    gtest_discover_tests(${target} TEST_PREFIX "${target}." PROPERTIES TIMEOUT 30)
  endforeach()
endif()

# Permanent multi-seat ownership, negotiation, server-boundary and trace contracts.
if(UNIX)
  foreach(target native_slot_groups_test native_slot_group_wire_test native_slot_group_server_test native_authority_recording_test)
    add_executable(${target} ${target}.cpp)
    configure_test_target(${target})
    target_link_libraries(${target} PRIVATE football_test_native_recovery Threads::Threads)
    gtest_discover_tests(${target} TEST_PREFIX "${target}." PROPERTIES TIMEOUT 30)
  endforeach()
endif()

# Measured transport lead and cadence contracts retain regression witnesses.
add_executable(native_input_rtt_test native_input_rtt_test.cpp)
configure_test_target(native_input_rtt_test)
gtest_discover_tests(native_input_rtt_test TEST_PREFIX "native_input_rtt_test." PROPERTIES TIMEOUT 30)

# 2026-09-24: the real training observation layout is testable without RLtools.
add_library(rl_observation_static_contract OBJECT rl_observation_static_contract.cpp)
target_include_directories(rl_observation_static_contract PRIVATE ${ENGINE_SRC})
add_executable(engine_rl_observation_contract engine_rl_observation_contract.cpp)
target_include_directories(engine_rl_observation_contract PRIVATE ${ENGINE_SRC})
add_test(NAME rl_observation_contract COMMAND engine_rl_observation_contract)
set_tests_properties(rl_observation_contract PROPERTIES TIMEOUT 30)

# ===== RLtools PPO 训练 POC =====
option(ENABLE_RLTOOLS "Build RLtools PPO training POC" OFF)
if(ENABLE_RLTOOLS)
  set(RLTOOLS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../rl-tools/include")
  add_executable(rl_football_training
    rl_football_training.cpp
  )
  target_include_directories(rl_football_training PRIVATE
    ${ENGINE_SRC}
    ${RLTOOLS_DIR}
  )
  target_compile_definitions(rl_football_training PRIVATE
    RL_TOOLS_USE_THIS_VERSION=1
  )
  target_compile_options(rl_football_training PRIVATE -O3 -ffast-math)
  message(STATUS "RLtools PPO training POC enabled")
endif()

# ===== 构建统计 =====
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "Unity build: ${CMAKE_UNITY_BUILD}")
message(STATUS "PCH enabled: ${ENABLE_PCH}")
# 2026-09-09: derive the count from the targets actually declared.
# message(STATUS "Test targets: 14")
get_property(review_targets DIRECTORY PROPERTY BUILDSYSTEM_TARGETS)
list(LENGTH review_targets review_target_count)
message(STATUS "Build targets: ${review_target_count}")
