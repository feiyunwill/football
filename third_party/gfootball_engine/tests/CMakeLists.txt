# C++ 单元测试（gtest），通过 FetchContent 自动下载 GoogleTest。
# 构建：cmake -S tests -B build_tests && cmake --build build_tests -j 1
# 运行：./build_tests/frame_sync_test

cmake_minimum_required(VERSION 3.14)
project(gfootball_tests CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

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

# 引擎源码目录
set(ENGINE_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../src")

# ===== 帧同步协议测试 =====
add_executable(frame_sync_test
  frame_sync_test.cpp
)
target_include_directories(frame_sync_test PRIVATE ${ENGINE_SRC})
target_link_libraries(frame_sync_test PRIVATE gtest_main)

# ===== ECS 组件测试 =====
add_executable(ecs_test
  ecs_test.cpp
)
target_include_directories(ecs_test PRIVATE ${ENGINE_SRC})
target_link_libraries(ecs_test PRIVATE gtest_main)

# ===== FixedPoint 定点数测试 =====
add_executable(fixed_point_test
  fixed_point_test.cpp
)
target_include_directories(fixed_point_test PRIVATE ${ENGINE_SRC})
target_link_libraries(fixed_point_test PRIVATE gtest_main)

# ===== FixedPoint 跨平台确定性测试 =====
add_executable(fixed_point_determinism_test
  fixed_point_determinism_test.cpp
)
target_include_directories(fixed_point_determinism_test PRIVATE ${ENGINE_SRC})
target_link_libraries(fixed_point_determinism_test PRIVATE gtest_main)

# ===== P2-Phase1: PlayerPhysicsComponent 测试 =====
add_executable(ecs_physics_sync_test
  ecs_physics_sync_test.cpp
)
target_include_directories(ecs_physics_sync_test PRIVATE ${ENGINE_SRC})
target_link_libraries(ecs_physics_sync_test PRIVATE gtest_main)

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

# 自动发现测试
gtest_discover_tests(frame_sync_test)
gtest_discover_tests(ecs_test)
gtest_discover_tests(fixed_point_test)
gtest_discover_tests(fixed_point_determinism_test)
gtest_discover_tests(ecs_physics_sync_test)
