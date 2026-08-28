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

# ===== P2-Phase1: PlayerPhysicsComponent 测试 =====
add_executable(ecs_physics_sync_test
  ecs_physics_sync_test.cpp
)
target_include_directories(ecs_physics_sync_test PRIVATE ${ENGINE_SRC})
target_link_libraries(ecs_physics_sync_test PRIVATE gtest_main)

# 自动发现测试
gtest_discover_tests(frame_sync_test)
gtest_discover_tests(ecs_test)
gtest_discover_tests(ecs_physics_sync_test)
