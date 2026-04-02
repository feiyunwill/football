# Copyright 2019 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# 2026-04-02 原因：无 SDL2Config.cmake 的发行版（如 Rocky/RHEL 仅装 -devel rpm）用 MODULE 查找

include(FindPackageHandleStandardArgs)

find_path(SDL2_INCLUDE_DIR SDL.h
  HINTS
    ENV SDL2DIR
  PATH_SUFFIXES SDL2 include/SDL2 include
  PATHS
    ~/Library/Frameworks
    /Library/Frameworks
    /usr/local
    /usr
)

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
  set(_sdl2_lib_suffix lib/x64)
else()
  set(_sdl2_lib_suffix lib/x86)
endif()

find_library(SDL2_LIBRARY
  NAMES SDL2
  HINTS
    ENV SDL2DIR
  PATH_SUFFIXES lib lib64 ${_sdl2_lib_suffix}
  PATHS
    ~/Library/Frameworks
    /Library/Frameworks
    /usr/local
    /usr
)

find_package_handle_standard_args(SDL2 DEFAULT_MSG SDL2_LIBRARY SDL2_INCLUDE_DIR)

if(SDL2_FOUND)
  set(SDL2_LIBRARIES ${SDL2_LIBRARY})
  set(SDL2_INCLUDE_DIRS ${SDL2_INCLUDE_DIR})
endif()

mark_as_advanced(SDL2_LIBRARY SDL2_INCLUDE_DIR)
