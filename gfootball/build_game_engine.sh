#!/bin/bash
# Copyright 2019 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -e

# 2026-08-26 原因：切换到 gcc-toolset-15（GCC 15.2，完整 C++23 / C++26 flag），
# 存在时置于 PATH 前列，使 cmake 探测与后续 make 都使用 GTS-15 编译器；
# 系统默认 gcc 11 不支持 C++23。GTS-16 尚未进入 Rocky 9 仓库，进源后再升级。
if [ -d /opt/rh/gcc-toolset-15/root/usr/bin ]; then
    export PATH=/opt/rh/gcc-toolset-15/root/usr/bin:$PATH
fi

LIB_EXTENSION="so"

if [[ "$OSTYPE" == "darwin"* ]] ; then
    LIB_EXTENSION="dylib"
fi

# Take into account # of cores and available RAM for deciding on compilation parallelism.
# TODO: Try importing psutil and if failed fall back to 1 thread
PARALLELISM=$(python3 -c 'import psutil; import multiprocessing as mp; print(int(max(1,min((psutil.virtual_memory().available/1000000000-1)/0.5, mp.cpu_count()))))')

# Delete pre-existing version of CMakeCache.txt to make 'python3 -m pip install' work.
rm -f third_party/gfootball_engine/CMakeCache.txt
pushd third_party/gfootball_engine && cmake . && make -j $PARALLELISM && popd
pushd third_party/gfootball_engine && ln -sf libgame.$LIB_EXTENSION _gameplayfootball.so && popd
