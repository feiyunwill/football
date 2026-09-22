# 2026-09-09: CMake 4 no longer accepts compatibility with 3.4.
# cmake_minimum_required(VERSION 3.4)
cmake_minimum_required(VERSION 3.14)

option(BUILD_PYTHON_BINDINGS "Build the Python extension (not required by native programs)" ON)

if(WIN32)
  # Check for required Environment variables
  if(NOT DEFINED CMAKE_GENERATOR_PLATFORM)
    message(FATAL_ERROR "CMAKE_GENERATOR_PLATFORM is not defined. Add -Ax64 or -AWin32 to cmake command")
  elseif(NOT DEFINED ENV{VCPKG_ROOT})
    message(FATAL_ERROR "VCPKG_ROOT is not defined. Set the location of vcpkg")
  elseif(BUILD_PYTHON_BINDINGS AND NOT DEFINED ENV{PY_VERSION})  # PY_VERSION has to be X.Y, e.g. 3.9
    message(FATAL_ERROR "PY_VERSION is not defined. Define Python version that will be used, e.g. 3.9")
  endif()

  if(${CMAKE_GENERATOR_PLATFORM} STREQUAL Win32)
    set(VCPKG_TARGET_TRIPLET "x86-windows")
  elseif(${CMAKE_GENERATOR_PLATFORM} STREQUAL x64)
    set(VCPKG_TARGET_TRIPLET "x64-windows")
  else()
    message(FATAL_ERROR "Unsupported Generator Platform, only Win32 or x64 are supported")
  endif()

  set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake")
  if(BUILD_PYTHON_BINDINGS)
    set(VCPKG_MANIFEST_DIR "${CMAKE_SOURCE_DIR}/vcpkg_manifests/py$ENV{PY_VERSION}")
  endif()
  set(CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS TRUE)
  # Windows requires the library to have the same name as the module
  set(OUTPUT_LIB_NAME _gameplayfootball)
else()  # UNIX
  set(OUTPUT_LIB_NAME game)
  set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH} "${CMAKE_SOURCE_DIR}/CMakeModules")
endif()

project(gameplayfootball)
set(PACKAGE gameplayfootball)

# 全工程现代化：统一 C++ 标准，兼顾兼容性与现代特性
# 参见 doc/compile_engine.md 与 CXX_STANDARD.md
# set(CMAKE_CXX_STANDARD 14)
# set(CMAKE_CXX_STANDARD 20)
# 2026-08-26 升级原因：工具链切换到 gcc-toolset-15（GCC 15.2），C++23 支持完整，
# 按仓库规则「目标 C++23 优先」从 20 升级；需配合 GTS-15 编译器重新 cmake 配置
set(CMAKE_CXX_STANDARD 23)
# 2026-09-09: silent standard fallback cannot compile the C++23 implementation.
# set(CMAKE_CXX_STANDARD_REQUIRED OFF)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# 2026-04-02 原因：生成 compile_commands.json 供 clangd/ccls 等 LSP 解析 include/宏（位于 ${CMAKE_BINARY_DIR}/compile_commands.json）
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# 2026-09-09: let CMake configurations control optimization/debug symbols.
# set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${GCC_COVERAGE_COMPILE_FLAGS} -fPIC -g -O3")
# set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fPIC -O3 -g")
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_BUILD_RPATH_USE_ORIGIN ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build configuration" FORCE)
endif()
if(UNIX)
  set(OpenGL_GL_PREFERENCE GLVND)
endif()
find_package(Threads REQUIRED)

# 2026-09-09: instrument every engine translation unit and its executable hosts.
option(FOOTBALL_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
if(FOOTBALL_ENABLE_SANITIZERS)
  if(NOT CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang" OR WIN32)
    message(FATAL_ERROR "Engine sanitizer acceptance requires GCC/Clang on Unix")
  endif()
  add_compile_options(-fsanitize=address,undefined -fno-sanitize-recover=all
                      -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address,undefined -fno-sanitize-recover=all)
endif()

# Find required libraries
FIND_PACKAGE(OpenGL REQUIRED)
include_directories(${OPENGL_INCLUDE_DIR})

# 2026-04-02 原因：先尝试 CONFIG（vcpkg）；失败则用 CMakeModules/FindSDL2.cmake（无 SDL2Config 的 Linux）
# FIND_PACKAGE(SDL2 REQUIRED)
find_package(SDL2 QUIET CONFIG)
if(NOT SDL2_FOUND)
  find_package(SDL2 MODULE REQUIRED)
endif()
include_directories(${SDL2_INCLUDE_DIRS})

if(UNIX AND NOT APPLE)
  FIND_PACKAGE(EGL REQUIRED)
  include_directories(${EGL_INCLUDE_DIR})
endif()

if(WIN32)
  FIND_PACKAGE(SDL2-image REQUIRED)
  FIND_PACKAGE(SDL2-ttf REQUIRED)
  FIND_PACKAGE(SDL2-gfx REQUIRED)
else()  # Unix
  FIND_PACKAGE(SDL2_image REQUIRED)
  FIND_PACKAGE(SDL2_ttf REQUIRED)
  FIND_PACKAGE(SDL2_gfx REQUIRED)
endif()

include_directories(${SDL2_IMAGE_DIRS})
include_directories(${SDL2_TTF_DIRS})
include_directories(${SDL2_GFX_DIRS})

# 2026-09-09: a native-only configuration never discovers or downloads Python bindings.
if(BUILD_PYTHON_BINDINGS)
if(UNIX)
  if(${CMAKE_VERSION} VERSION_GREATER_EQUAL "3.12")
    # 2026-04-02 原因：pybind11 需要 Python Interpreter 组件，仅 Development 会配置失败
    # find_package(Python COMPONENTS Development REQUIRED)
    find_package(Python COMPONENTS Development Interpreter REQUIRED)
  else()
    # Starting from CMake 3.12 FindPythonLibs was deprecated in favour of FindPython.
    # But Ubuntu 18.04 and other older distributions are shipped with CMake version < 3.12,
    # so we have to support the old behaviour for some time.
    find_package(PythonLibs 3 REQUIRED)
    string(REPLACE "." ";" VERSION_LIST ${PYTHONLIBS_VERSION_STRING})
    list(GET VERSION_LIST 0 Python_VERSION_MAJOR)
    list(GET VERSION_LIST 1 Python_VERSION_MINOR)
    set(Python_INCLUDE_DIRS ${PYTHON_INCLUDE_DIRS})
    set(Python_LIBRARIES ${PYTHON_LIBRARIES})
  endif()
elseif(WIN32)
  # find_package (Python COMPONENTS Development)
  # FindPython package searches for system-wide python installations first.
  # It was improved only recently (Jan 2021), so we can't use it for earlier py versions:
  # (see https://github.com/microsoft/vcpkg/pull/15221 )
  # To avoid version mismatch we point to vcpkg's libs directly
  string(REPLACE "." ";" VERSION_LIST $ENV{PY_VERSION})
  list(GET VERSION_LIST 0 Python_VERSION_MAJOR)
  list(GET VERSION_LIST 1 Python_VERSION_MINOR)
  set(Python_INCLUDE_DIRS "${CMAKE_BINARY_DIR}/vcpkg_installed/${VCPKG_TARGET_TRIPLET}/include/python${Python_VERSION_MAJOR}.${Python_VERSION_MINOR}")
  set(Python_LIBRARIES "${CMAKE_BINARY_DIR}/vcpkg_installed/${VCPKG_TARGET_TRIPLET}/lib/python${Python_VERSION_MAJOR}${Python_VERSION_MINOR}.lib")
endif()

message("Using Python: ${Python_VERSION_MAJOR}.${Python_VERSION_MINOR}")
# 2026-09-09: Python include paths belong only to the binding target.
# include_directories(${Python_INCLUDE_DIRS})
if(NOT WIN32 AND ${CMAKE_VERSION} VERSION_GREATER_EQUAL "3.15")
  set(Py_TARGETS Python::Module)
else()
  set(Py_TARGETS ${Python_LIBRARIES})
endif()

# pybind11 (replaces Boost.Python)
include(FetchContent)
FetchContent_Declare(
  pybind11
  GIT_REPOSITORY https://github.com/pybind/pybind11.git
  GIT_TAG        v2.11.1
)
set(PYBIND11_FINDPYTHON ON)
# 2026-09-09: allow a toolchain-provided binding library for newer Python ABIs.
# FetchContent_MakeAvailable(pybind11)
find_package(pybind11 CONFIG QUIET)
if(NOT pybind11_FOUND)
  FetchContent_MakeAvailable(pybind11)
endif()
message("Using pybind11 for Python bindings")
endif()


# 2026-08-26 移除 Boost（原因）：filesystem/thread/bind/shared_ptr 均已迁移到 std；
# 引擎 so 本身只剩 Boost 头文件需求（frame_sync 的 asio），不再链接任何 Boost 库。
# 保留 system 组件仅为下方 frame_sync_* 独立可执行目标的 Boost::system 导入目标
#（Boost≥1.69 asio 头文件即用，该链接项是历史兼容写法）。
# FIND_PACKAGE(Boost REQUIRED COMPONENTS thread system filesystem)
FIND_PACKAGE(Boost REQUIRED COMPONENTS system)
include_directories(${Boost_INCLUDE_DIRS})

include_directories(${PROJECT_SOURCE_DIR}/src)
include_directories(${PROJECT_SOURCE_DIR}/src/cmake)

# Include the sources
include(sources.cmake)

add_library(baselib OBJECT ${BASE_SOURCES} ${BASE_HEADERS}
   ${BASE_GEOMETRY_HEADERS} ${BASE_MATH_HEADERS})
add_library(systemsgraphicslib OBJECT ${SYSTEMS_GRAPHICS_SOURCES} ${SYSTEMS_COMMON_HEADERS}
   ${SYSTEMS_GRAPHICS_HEADERS} ${SYSTEMS_GRAPHICS_OBJECTS_HEADERS}
   ${SYSTEMS_GRAPHICS_RESOURCES_HEADERS} ${SYSTEMS_GRAPHICS_RENDERING_HEADERS})
add_library(loaderslib OBJECT ${LOADERS_SOURCES} ${LOADERS_HEADERS} ${MANAGERS_HEADERS})
add_library(typeslib OBJECT ${TYPES_SOURCES} ${TYPES_HEADERS})
add_library(scenelib OBJECT ${SCENE_SOURCES} ${SCENE_HEADERS}
   ${SCENE2D_HEADERS} ${SCENE3D_HEADERS} ${SCENE_OBJECTS_HEADERS}
   ${SCENE_RESOURCES_HEADERS})
add_library(utilslib OBJECT ${UTILS_SOURCES} ${UTILS_HEADERS}
   ${UTILS_EXT_HEADERS})
add_library(gui2lib OBJECT ${UTILS_GUI2_SOURCES} ${UTILS_GUI2_HEADERS}
   ${UTILS_GUI2_WIDGETS_HEADERS})

# Join all created static libraries into a single static or shared one.
set(OWN_LIBRARIES $<TARGET_OBJECTS:baselib> # $<TARGET_OBJECTS:systemscommonlib>
   $<TARGET_OBJECTS:systemsgraphicslib> $<TARGET_OBJECTS:loaderslib>
   $<TARGET_OBJECTS:typeslib> $<TARGET_OBJECTS:scenelib>
   $<TARGET_OBJECTS:utilslib> $<TARGET_OBJECTS:gui2lib>)

# Compile it as multiple static libraries
add_library(blunted2 ${BLUNTED_CORE_SOURCES} ${BLUNTED_CORE_HEADERS} ${OWN_LIBRARIES})
add_library(gamelib ${GAME_SOURCES} ${GAME_HEADERS})
add_library(menulib ${MENU_SOURCES} ${MENU_HEADERS})
add_library(datalib ${DATA_SOURCES} ${DATA_HEADERS})

if(UNIX)
  set(SDL2_LIBS_ALL ${SDL2_IMAGE_LIBRARIES} ${SDL2_TTF_LIBRARIES} ${SDL2_GFX_LIBRARIES} ${SDL2_LIBRARIES})
elseif(WIN32)
  set(SDL2_LIBS_ALL SDL2::SDL2 SDL2::SDL2_image SDL2::SDL2_ttf SDL2::SDL2_gfx SDL2::SDL2main)
endif()

# 2026-09-09: the native engine owns runtime code; ai.cpp is only a binding adapter.
# set(LIBRARIES gamelib menulib datalib blunted2
#    # 2026-08-26 移除 Boost：Boost::filesystem/system/thread 链接项随组件精简一并移除
#    # （asio 自 Boost 1.69 起头文件即用，frame_sync_* 独立目标保留各自的 Boost::system）。
#    pybind11::module ${Py_TARGETS} ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES})
#
# add_library(${OUTPUT_LIB_NAME} SHARED ${CORE_SOURCES} ${CORE_HEADERS} ${AI_HEADERS} ${AI_SOURCES})
# target_link_libraries(${OUTPUT_LIB_NAME} ${LIBRARIES})
#
# if(WIN32)
#   set_target_properties(${OUTPUT_LIB_NAME} PROPERTIES SUFFIX ".pyd")
# endif()
#
set(ENGINE_PLATFORM_LIBRARIES ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES} Threads::Threads)
add_library(football_engine SHARED ${CORE_SOURCES} ${CORE_HEADERS} ${AI_HEADERS} ${AI_SOURCES})
target_link_libraries(football_engine PRIVATE gamelib menulib datalib blunted2
                                      PUBLIC ${ENGINE_PLATFORM_LIBRARIES})
target_include_directories(football_engine PUBLIC ${PROJECT_SOURCE_DIR}/src)
if(BUILD_PYTHON_BINDINGS)
  add_library(${OUTPUT_LIB_NAME} SHARED ${PYTHON_BINDING_SOURCES})
  target_link_libraries(${OUTPUT_LIB_NAME} PRIVATE football_engine pybind11::module ${Py_TARGETS})
  target_include_directories(${OUTPUT_LIB_NAME} PRIVATE ${Python_INCLUDE_DIRS})
  # Wheels place the engine library next to the extension, including when moved.
  if(APPLE)
    set_target_properties(${OUTPUT_LIB_NAME} PROPERTIES BUILD_WITH_INSTALL_RPATH ON INSTALL_RPATH "@loader_path")
  elseif(UNIX)
    set_target_properties(${OUTPUT_LIB_NAME} PROPERTIES BUILD_WITH_INSTALL_RPATH ON INSTALL_RPATH "$ORIGIN")
  endif()
  if(WIN32)
    set_target_properties(${OUTPUT_LIB_NAME} PROPERTIES SUFFIX ".pyd")
  endif()
endif()

# ----- 帧同步联机（UDP + 真实 GameEnv）-----
# 2026-09-09: callers can isolate artifacts from different build configurations.
# set(BIN_DIR ${PROJECT_SOURCE_DIR}/../bin)
set(FOOTBALL_RUNTIME_OUTPUT_DIRECTORY "${PROJECT_SOURCE_DIR}/../bin" CACHE PATH "Native executable directory")
set(BIN_DIR "${FOOTBALL_RUNTIME_OUTPUT_DIRECTORY}")

add_executable(football_server src/frame_sync/asio_server_engine.cpp)
target_include_directories(football_server PRIVATE ${PROJECT_SOURCE_DIR}/src)
# 2026-09-09: native programs link one engine, without Python or duplicated static libraries.
# target_link_libraries(football_server PRIVATE
# -Wl,--no-as-needed
# ${OUTPUT_LIB_NAME}
# gamelib menulib datalib blunted2
# ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES}
# ${Python_LIBRARIES}
# Boost::system
# pthread
# )
target_link_libraries(football_server PRIVATE football_engine Boost::system)
set_target_properties(football_server PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

add_executable(football_client src/frame_sync/integrated_client_udp.cpp)
target_include_directories(football_client PRIVATE ${PROJECT_SOURCE_DIR}/src)
# 2026-09-09: native programs link one engine, without Python or duplicated static libraries.
# target_link_libraries(football_client PRIVATE
# -Wl,--no-as-needed
# ${OUTPUT_LIB_NAME}
# gamelib menulib datalib blunted2
# ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES}
# ${Python_LIBRARIES}
# Boost::system
# pthread
# )
target_link_libraries(football_client PRIVATE football_engine Boost::system)
set_target_properties(football_client PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-09: compile the TCP implementation that carries Phase 16/17 features.
get_target_property(FRAME_SYNC_ENGINE_LIBRARIES football_client LINK_LIBRARIES)
add_executable(football_client_tcp src/frame_sync/integrated_client.cpp)
add_executable(football_server_tcp src/frame_sync/integrated_server.cpp)
foreach(target football_client_tcp football_server_tcp)
  target_include_directories(${target} PRIVATE ${PROJECT_SOURCE_DIR}/src)
  target_link_libraries(${target} PRIVATE ${FRAME_SYNC_ENGINE_LIBRARIES})
  set_target_properties(${target} PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})
endforeach()

add_executable(football_lobby src/frame_sync/lobby_server.cpp)
target_include_directories(football_lobby PRIVATE ${PROJECT_SOURCE_DIR}/src)
target_link_libraries(football_lobby PRIVATE Boost::system)
set_target_properties(football_lobby PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# ----- Headless match runner（AI vs AI 无头比赛）-----
add_executable(headless_match src/frame_sync/headless_match.cpp)
target_include_directories(headless_match PRIVATE ${PROJECT_SOURCE_DIR}/src)
# 2026-09-09: native programs link one engine, without Python or duplicated static libraries.
# target_link_libraries(headless_match PRIVATE
# -Wl,--no-as-needed
# ${OUTPUT_LIB_NAME}
# gamelib menulib datalib blunted2
# ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES}
# ${Python_LIBRARIES}
# pthread
# )
target_link_libraries(headless_match PRIVATE football_engine)
set_target_properties(headless_match PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# ----- Standalone single-player game（键盘 vs AI，无需网络）-----
add_executable(standalone_game src/frame_sync/standalone_game.cpp)
target_include_directories(standalone_game PRIVATE ${PROJECT_SOURCE_DIR}/src)
# 2026-09-09: native programs link one engine, without Python or duplicated static libraries.
# target_link_libraries(standalone_game PRIVATE
# -Wl,--no-as-needed
# ${OUTPUT_LIB_NAME}
# gamelib menulib datalib blunted2
# ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES}
# ${Python_LIBRARIES}
# pthread
# )
target_link_libraries(standalone_game PRIVATE football_engine)
set_target_properties(standalone_game PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-09: real-match contracts are distinct from header-only unit tests.
add_executable(engine_state_contract EXCLUDE_FROM_ALL ${ENGINE_STATE_CONTRACT_SOURCES})
target_link_libraries(engine_state_contract PRIVATE football_engine)
set_target_properties(engine_state_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

add_executable(engine_lifetime_contract EXCLUDE_FROM_ALL ${ENGINE_LIFETIME_CONTRACT_SOURCES})
target_link_libraries(engine_lifetime_contract PRIVATE football_engine)
set_target_properties(engine_lifetime_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-09: malformed-state recovery and actual graphics/logic isolation.
add_executable(engine_simulation_contract EXCLUDE_FROM_ALL ${ENGINE_SIMULATION_CONTRACT_SOURCES})
target_link_libraries(engine_simulation_contract PRIVATE football_engine)
set_target_properties(engine_simulation_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

add_executable(engine_architecture_contract EXCLUDE_FROM_ALL ${ENGINE_ARCHITECTURE_CONTRACT_SOURCES})
target_link_libraries(engine_architecture_contract PRIVATE football_engine)
set_target_properties(engine_architecture_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-09: real GameEnv rollback/replay with constrained memory.
add_executable(engine_memory_contract EXCLUDE_FROM_ALL ${ENGINE_MEMORY_CONTRACT_SOURCES})
target_link_libraries(engine_memory_contract PRIVATE football_engine)
set_target_properties(engine_memory_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

add_executable(engine_match_benchmark EXCLUDE_FROM_ALL ${ENGINE_MATCH_BENCHMARK_SOURCES})
target_link_libraries(engine_match_benchmark PRIVATE football_engine)
set_target_properties(engine_match_benchmark PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-13: independent long-match acceptance executable.
add_executable(engine_soak_benchmark EXCLUDE_FROM_ALL ${ENGINE_SOAK_BENCHMARK_SOURCES})
target_link_libraries(engine_soak_benchmark PRIVATE football_engine)
set_target_properties(engine_soak_benchmark PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-09: validate animation query allocation changes against the native core.
add_executable(engine_animation_query_contract EXCLUDE_FROM_ALL ${ENGINE_ANIMATION_QUERY_CONTRACT_SOURCES})
target_link_libraries(engine_animation_query_contract PRIVATE football_engine)
set_target_properties(engine_animation_query_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-13: exact differential tests for the measured arrival-time hotspot.
add_executable(engine_ai_reachability_contract EXCLUDE_FROM_ALL ${ENGINE_AI_REACHABILITY_CONTRACT_SOURCES})
target_link_libraries(engine_ai_reachability_contract PRIVATE football_engine)
set_target_properties(engine_ai_reachability_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-09: optional Linux diagnostic interposer; no production target links it.
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  add_library(engine_hotspot_profile SHARED EXCLUDE_FROM_ALL ${ENGINE_HOTSPOT_PROFILE_SOURCES})
  target_link_libraries(engine_hotspot_profile PRIVATE ${CMAKE_DL_LIBS})
endif()

# ----- RLtools PPO 训练（接入真实 GameEnv）-----
option(BUILD_RL_TRAINING "Build RLtools PPO training with real engine" OFF)
if(BUILD_RL_TRAINING)
  set(RLTOOLS_DIR "${PROJECT_SOURCE_DIR}/../third_party/rl-tools/include")
  add_executable(rl_football_training
    src/frame_sync/rl_training/training.cpp
  )
  target_include_directories(rl_football_training PRIVATE
    ${PROJECT_SOURCE_DIR}/src
    ${RLTOOLS_DIR}
  )
  target_compile_definitions(rl_football_training PRIVATE
    RL_TOOLS_USE_THIS_VERSION=1
  )
  # 2026-09-09: native programs link one engine, without Python or duplicated static libraries.
  # target_link_libraries(rl_football_training PRIVATE
  # -Wl,--no-as-needed
  # ${OUTPUT_LIB_NAME}
  # gamelib menulib datalib blunted2
  # ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES}
  # ${Python_LIBRARIES}
  # Boost::system
  # stdc++fs quadmath
  # )
  target_link_libraries(rl_football_training PRIVATE football_engine Boost::system)
  target_compile_options(rl_football_training PRIVATE -O3 -ffast-math)
  message(STATUS "RLtools PPO training with real engine enabled")
endif()

# 2026-09-09: real GameEnv TCP capacity, handover, snapshot and hash acceptance.
add_executable(engine_tcp_contract EXCLUDE_FROM_ALL ${ENGINE_TCP_CONTRACT_SOURCES})
target_link_libraries(engine_tcp_contract PRIVATE football_engine Boost::system)
set_target_properties(engine_tcp_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-09: real renderer exception recovery and bounded runtime output.
add_executable(engine_runtime_contract EXCLUDE_FROM_ALL ${ENGINE_RUNTIME_CONTRACT_SOURCES})
target_link_libraries(engine_runtime_contract PRIVATE football_engine)
set_target_properties(engine_runtime_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-10: native display attachments use real skeletons, objects and OpenGL.
add_executable(engine_render_pose_contract EXCLUDE_FROM_ALL ${ENGINE_RENDER_POSE_CONTRACT_SOURCES})
target_link_libraries(engine_render_pose_contract PRIVATE football_engine)
set_target_properties(engine_render_pose_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-13: capture policy uses actual GameEnv pixels and serialization.
add_executable(engine_frame_capture_contract EXCLUDE_FROM_ALL ${ENGINE_FRAME_CAPTURE_CONTRACT_SOURCES})
target_link_libraries(engine_frame_capture_contract PRIVATE football_engine)
set_target_properties(engine_frame_capture_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-09: shared TCP client resumes a real GameEnv server.
add_executable(engine_tcp_client_contract EXCLUDE_FROM_ALL ${ENGINE_TCP_CLIENT_CONTRACT_SOURCES})
target_link_libraries(engine_tcp_client_contract PRIVATE football_engine Boost::system)
set_target_properties(engine_tcp_client_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-13: formal input gate builds the same canonical headers as product mains.
# X11 test dependencies may be installed or supplied as an isolated dependency root.
set(FOOTBALL_TEST_X11_ROOT "" CACHE PATH "Root containing usr/include and usr/lib for XTEST fixtures")
foreach(contract IN ITEMS engine_native_input_buffer_contract engine_native_input_gameenv_contract
    engine_native_input_admission_contract engine_native_presentation_contract
    engine_server_input_window_contract engine_native_clock_replay_contract
# 2026-09-13: product contract runs against both actual instrumented and Release engines.
#     engine_native_sdl_input_contract)
# 2026-09-13: build concurrent publication against both engine configurations.
#     engine_native_sdl_input_contract engine_native_match_contract)
# 2026-09-13: sample UI input at bounded render work opportunities.
#     engine_native_sdl_input_contract engine_native_match_contract engine_native_transport_pump_contract)
    engine_native_sdl_input_contract engine_native_match_contract engine_native_transport_pump_contract
# 2026-09-13: bind sampled input to fixed simulation deadlines.
#     engine_render_service_contract)
# 2026-09-13: main-thread UI lifetime and input handoff are mandatory native contracts.
#    engine_render_service_contract engine_native_input_timeline_contract)
# 2026-09-13: retain actual AI selection transition as a required native contract.
#     engine_render_service_contract engine_native_input_timeline_contract engine_native_ui_owner_contract engine_native_publication_clock_contract)
    engine_render_service_contract engine_native_input_timeline_contract engine_native_ui_owner_contract engine_native_publication_clock_contract engine_native_bot_selection_contract)
  string(TOUPPER "${contract}" contract_upper)
  add_executable(${contract} EXCLUDE_FROM_ALL ${${contract_upper}_SOURCES})
  target_link_libraries(${contract} PRIVATE football_engine)
  set_target_properties(${contract} PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})
endforeach()
add_library(engine_native_window_trace MODULE EXCLUDE_FROM_ALL ${ENGINE_NATIVE_WINDOW_TRACE_SOURCES})
target_link_libraries(engine_native_window_trace PRIVATE football_engine ${CMAKE_DL_LIBS})
set_target_properties(engine_native_window_trace PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/input-tests")
if(FOOTBALL_TEST_X11_ROOT)
  target_include_directories(engine_native_sdl_input_contract PRIVATE "${FOOTBALL_TEST_X11_ROOT}/usr/include")
  target_include_directories(engine_native_window_trace PRIVATE "${FOOTBALL_TEST_X11_ROOT}/usr/include")
  target_link_directories(engine_native_sdl_input_contract PRIVATE "${FOOTBALL_TEST_X11_ROOT}/usr/lib")
endif()
target_link_libraries(engine_native_sdl_input_contract PRIVATE Xtst X11)

# 2026-09-14: real control animations cover idle, moving and fast-ball touch decisions.
add_executable(engine_ai_touch_contract EXCLUDE_FROM_ALL ${ENGINE_AI_TOUCH_CONTRACT_SOURCES})
target_link_libraries(engine_ai_touch_contract PRIVATE football_engine)
set_target_properties(engine_ai_touch_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-14: shared tactical state, role decisions and real takeover replay.
add_executable(engine_ai_tactics_contract EXCLUDE_FROM_ALL ${ENGINE_AI_TACTICS_CONTRACT_SOURCES})
target_link_libraries(engine_ai_tactics_contract PRIVATE football_engine)
set_target_properties(engine_ai_tactics_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})
add_executable(engine_ai_tactics_roles_contract EXCLUDE_FROM_ALL ${ENGINE_AI_TACTICS_ROLES_CONTRACT_SOURCES})
target_link_libraries(engine_ai_tactics_roles_contract PRIVATE football_engine)
set_target_properties(engine_ai_tactics_roles_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})
add_executable(engine_ai_tactical_state_contract EXCLUDE_FROM_ALL ${ENGINE_AI_TACTICAL_STATE_CONTRACT_SOURCES})
target_link_libraries(engine_ai_tactical_state_contract PRIVATE football_engine)
set_target_properties(engine_ai_tactical_state_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})
add_executable(engine_native_tactics_replay_contract EXCLUDE_FROM_ALL ${ENGINE_NATIVE_TACTICS_REPLAY_CONTRACT_SOURCES})
target_link_libraries(engine_native_tactics_replay_contract PRIVATE football_engine)
set_target_properties(engine_native_tactics_replay_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-14: recovery hashes use the existing OpenSSL 3 API; only transport hosts require it.
find_package(OpenSSL 3.0 REQUIRED COMPONENTS Crypto)
add_library(football_native_recovery STATIC ${FOOTBALL_NATIVE_RECOVERY_SOURCES})
target_link_libraries(football_native_recovery PRIVATE OpenSSL::Crypto)
target_include_directories(football_native_recovery PUBLIC ${PROJECT_SOURCE_DIR}/src)
set_target_properties(football_native_recovery PROPERTIES POSITION_INDEPENDENT_CODE ON)
# 2026-09-15: the actual recoverable TCP client also owns checkpoint journal digests.
# foreach(target football_server_tcp engine_tcp_contract engine_tcp_client_contract)
foreach(target football_server_tcp football_client_tcp engine_tcp_contract engine_tcp_client_contract)
  target_link_libraries(${target} PRIVATE football_native_recovery)
endforeach()
add_executable(engine_native_recovery_tcp_contract EXCLUDE_FROM_ALL ${ENGINE_NATIVE_RECOVERY_TCP_CONTRACT_SOURCES})
target_link_libraries(engine_native_recovery_tcp_contract PRIVATE football_engine Boost::system football_native_recovery)
set_target_properties(engine_native_recovery_tcp_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-15: persistent prepared-state, resource-unwind and authenticated admission contracts.
foreach(contract IN LISTS ENGINE_LOADING_CONTRACT_TARGETS)
  add_executable(${contract} EXCLUDE_FROM_ALL tests/${contract}.cpp)
  target_link_libraries(${contract} PRIVATE football_engine Boost::system football_native_recovery)
  set_target_properties(${contract} PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})
endforeach()

# 2026-09-22: exercise the shipped parser without a test-only replacement.
add_executable(engine_ase_parser_contract EXCLUDE_FROM_ALL ${ENGINE_ASE_PARSER_CONTRACT_SOURCES})
target_link_libraries(engine_ase_parser_contract PRIVATE football_engine)
set_target_properties(engine_ase_parser_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})

# 2026-09-22: actual shared-engine file reading, binary boundaries and errors.
add_executable(engine_file_read_contract EXCLUDE_FROM_ALL ${ENGINE_FILE_READ_CONTRACT_SOURCES})
target_link_libraries(engine_file_read_contract PRIVATE football_engine)
set_target_properties(engine_file_read_contract PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${BIN_DIR})
