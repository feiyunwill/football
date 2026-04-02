# Standalone build for frame sync C++ server/client (Boost.Asio only, no engine/SDL/OpenGL).
# Run from here: cmake . && make
# Or from engine root: cmake -S frame_sync_asio -B build_fs_asio && cmake --build build_fs_asio

# 与主引擎统一：C++20（见 third_party/gfootball_engine/CMakeLists.txt）
cmake_minimum_required(VERSION 3.10)
project(frame_sync_asio CXX)

set(CMAKE_CXX_STANDARD 20)

# 2026-04-02 原因：与主引擎一致，独立构建时也可生成 compile_commands.json 供 clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(Boost REQUIRED COMPONENTS system)
# Asio is header-only; Boost::system is needed on some platforms for linking.

set(ENGINE_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../src")

add_executable(frame_sync_server ${ENGINE_SRC}/frame_sync/asio_server.cpp)
target_include_directories(frame_sync_server PRIVATE ${ENGINE_SRC})
target_link_libraries(frame_sync_server PRIVATE Boost::system)

add_executable(frame_sync_client ${ENGINE_SRC}/frame_sync/asio_client.cpp)
target_include_directories(frame_sync_client PRIVATE ${ENGINE_SRC})
target_link_libraries(frame_sync_client PRIVATE Boost::system)

add_executable(frame_sync_server_udp ${ENGINE_SRC}/frame_sync/asio_server_udp.cpp)
target_include_directories(frame_sync_server_udp PRIVATE ${ENGINE_SRC})
target_link_libraries(frame_sync_server_udp PRIVATE Boost::system)

add_executable(frame_sync_client_udp ${ENGINE_SRC}/frame_sync/asio_client_udp.cpp)
target_include_directories(frame_sync_client_udp PRIVATE ${ENGINE_SRC})
target_link_libraries(frame_sync_client_udp PRIVATE Boost::system)
