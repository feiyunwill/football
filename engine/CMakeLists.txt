cmake_minimum_required(VERSION 3.4)

if(WIN32)
  # Check for required Environment variables
  if(NOT DEFINED CMAKE_GENERATOR_PLATFORM)
    message(FATAL_ERROR "CMAKE_GENERATOR_PLATFORM is not defined. Add -Ax64 or -AWin32 to cmake command")
  elseif(NOT DEFINED ENV{VCPKG_ROOT})
    message(FATAL_ERROR "VCPKG_ROOT is not defined. Set the location of vcpkg")
  elseif(NOT DEFINED ENV{PY_VERSION})  # PY_VERSION has to be X.Y, e.g. 3.9
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
  set(VCPKG_MANIFEST_DIR "${CMAKE_SOURCE_DIR}/vcpkg_manifests/py$ENV{PY_VERSION}")
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
set(CMAKE_CXX_STANDARD_REQUIRED OFF)
set(CMAKE_CXX_EXTENSIONS OFF)

# 2026-04-02 原因：生成 compile_commands.json 供 clangd/ccls 等 LSP 解析 include/宏（位于 ${CMAKE_BINARY_DIR}/compile_commands.json）
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(UNIX)
  set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${GCC_COVERAGE_COMPILE_FLAGS} -fPIC -g -O3")
  set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fPIC -O3 -g")
  set(OpenGL_GL_PREFERENCE GLVND)
endif(UNIX)

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
include_directories(${Python_INCLUDE_DIRS})
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
FetchContent_MakeAvailable(pybind11)
message("Using pybind11 for Python bindings")

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

set(LIBRARIES gamelib menulib datalib blunted2
   # 2026-08-26 移除 Boost：Boost::filesystem/system/thread 链接项随组件精简一并移除
   # （asio 自 Boost 1.69 起头文件即用，frame_sync_* 独立目标保留各自的 Boost::system）。
   pybind11::module ${Py_TARGETS} ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES})

add_library(${OUTPUT_LIB_NAME} SHARED ${CORE_SOURCES} ${CORE_HEADERS} ${AI_HEADERS} ${AI_SOURCES})
target_link_libraries(${OUTPUT_LIB_NAME} ${LIBRARIES})

if(WIN32)
  set_target_properties(${OUTPUT_LIB_NAME} PROPERTIES SUFFIX ".pyd")
endif()

# ----- Frame sync C++ server/client (Boost.Asio, no engine) -----
add_executable(frame_sync_server src/frame_sync/asio_server.cpp)
target_include_directories(frame_sync_server PRIVATE ${PROJECT_SOURCE_DIR}/src)
target_link_libraries(frame_sync_server PRIVATE Boost::system)

add_executable(frame_sync_client src/frame_sync/asio_client.cpp)
target_include_directories(frame_sync_client PRIVATE ${PROJECT_SOURCE_DIR}/src)
target_link_libraries(frame_sync_client PRIVATE Boost::system)

# ----- Frame sync over reliable UDP -----
add_executable(frame_sync_server_udp src/frame_sync/asio_server_udp.cpp)
target_include_directories(frame_sync_server_udp PRIVATE ${PROJECT_SOURCE_DIR}/src)
target_link_libraries(frame_sync_server_udp PRIVATE Boost::system)

add_executable(frame_sync_client_udp src/frame_sync/asio_client_udp.cpp)
target_include_directories(frame_sync_client_udp PRIVATE ${PROJECT_SOURCE_DIR}/src)
target_link_libraries(frame_sync_client_udp PRIVATE Boost::system)

# ----- 帧同步 C++ 服务端（接入真实 GameEnv，headless）-----
add_executable(frame_sync_server_engine src/frame_sync/asio_server_engine.cpp)
target_include_directories(frame_sync_server_engine PRIVATE ${PROJECT_SOURCE_DIR}/src)
target_link_libraries(frame_sync_server_engine PRIVATE
  -Wl,--no-as-needed
  ${OUTPUT_LIB_NAME}
  gamelib menulib datalib blunted2
  ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES}
  ${Python_LIBRARIES}
  Boost::system
  pthread
)

# ----- 集成帧同步客户端（接入真实 GameEnv）-----
add_executable(integrated_client src/frame_sync/integrated_client.cpp)
target_include_directories(integrated_client PRIVATE ${PROJECT_SOURCE_DIR}/src)
target_link_libraries(integrated_client PRIVATE
  -Wl,--no-as-needed
  ${OUTPUT_LIB_NAME}
  gamelib menulib datalib blunted2
  ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES}
  ${Python_LIBRARIES}
  Boost::system
  pthread
)

# ----- 集成帧同步服务端（接入真实 GameEnv，headless）-----
add_executable(integrated_server src/frame_sync/integrated_server.cpp)
target_include_directories(integrated_server PRIVATE ${PROJECT_SOURCE_DIR}/src)
target_link_libraries(integrated_server PRIVATE
  -Wl,--no-as-needed
  ${OUTPUT_LIB_NAME}
  gamelib menulib datalib blunted2
  ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES}
  ${Python_LIBRARIES}
  Boost::system
  pthread
)

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
  target_link_libraries(rl_football_training PRIVATE
    -Wl,--no-as-needed
    ${OUTPUT_LIB_NAME}
    gamelib menulib datalib blunted2
    ${SDL2_LIBS_ALL} ${EGL_LIBRARIES} ${OPENGL_LIBRARIES}
    ${Python_LIBRARIES}
    Boost::system
    stdc++fs quadmath
  )
  target_compile_options(rl_football_training PRIVATE -O3 -ffast-math)
  message(STATUS "RLtools PPO training with real engine enabled")
endif()
