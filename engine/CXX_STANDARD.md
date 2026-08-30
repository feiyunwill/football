# C++ 标准说明

## 当前设置

（2026-08-26 更新：工具链切换到 gcc-toolset-15 / GCC 15.2 后，两处标准从 20 升到 23）

- **主引擎**（本目录 `CMakeLists.txt`）：`CMAKE_CXX_STANDARD 23`
- **frame_sync_asio**（`frame_sync_asio/CMakeLists.txt`）：`CMAKE_CXX_STANDARD 23`
- **REQUIRED**：`OFF`，以便在编译器不支持 C++23 时自动降级。

## 工具链要求

- **gcc-toolset-15**（GCC 15.2，Rocky 9）：系统默认 gcc 11 不支持 C++23。
  - 走 `gfootball/build_game_engine.sh` 时脚本自动把 GTS-15 置于 PATH；
  - 手动 cmake/make 须导出：`export PATH=/opt/rh/gcc-toolset-15/root/usr/bin:$PATH`
    （或 `CC=/opt/rh/gcc-toolset-15/root/usr/bin/gcc CXX=/opt/rh/gcc-toolset-15/root/usr/bin/g++ cmake ...`）。
  - 切换编译器后 in-source 缓存失效：删除 `CMakeCache.txt` 与 `CMakeFiles/` 再重新配置。
- GTS-15 已接受 `-std=c++26`；C++26 特性按 libstdc++ 可用性渐进采用。

## 选择 C++23 的原因

- GCC 15 下 C++23 支持完整（含 `std::expected`、`std::print`、`if consteval`、多维下标等），
  符合项目 Modern C++ 学习方向与仓库「目标 C++23 优先」规则。
- 兼容性由 REQUIRED=OFF + 编译器探测兜底。

## 修改方式

在对应 `CMakeLists.txt` 中修改 `set(CMAKE_CXX_STANDARD 23)` 为所需标准即可；两处建议保持一致，便于帧同步与引擎共用代码时无 ABI 差异。

## compile_commands.json 与 clangd

主引擎与 `frame_sync_asio` 的 CMake 已设置 `CMAKE_EXPORT_COMPILE_COMMANDS ON`。配置成功后，在构建目录会生成 `compile_commands.json`（例如 `third_party/gfootball_engine/build/compile_commands.json`）。

- **clangd**：在引擎目录可执行 `ln -sf build/compile_commands.json .`（路径按本机 build 目录调整），或在工作区设置 `clangd.arguments` 增加 `--compile-commands-dir=…/build`。
- **勿将** 该文件提交仓库（根目录 `.gitignore` 已忽略引擎根下的 `compile_commands.json` 副本）。
