# C++ 标准说明

## 当前设置

- **主引擎**（本目录 `CMakeLists.txt`）：`CMAKE_CXX_STANDARD 20`
- **frame_sync_asio**（`frame_sync_asio/CMakeLists.txt`）：`CMAKE_CXX_STANDARD 20`
- **REQUIRED**：`OFF`，以便在编译器不支持 C++20 时自动降级。

## 选择 C++20 的原因

- 兼顾兼容性（主流 GCC/Clang/MSVC 均支持）与现代特性（如 `<=>`、concepts 部分支持、范围 for 等）。
- 与全工程现代化计划一致；若需 C++23，可在主引擎 `CMakeLists.txt` 中改为 `set(CMAKE_CXX_STANDARD 23)`。

## 修改方式

在对应 `CMakeLists.txt` 中修改 `set(CMAKE_CXX_STANDARD 20)` 为所需标准即可；两处建议保持一致，便于帧同步与引擎共用代码时无 ABI 差异。

## compile_commands.json 与 clangd

主引擎与 `frame_sync_asio` 的 CMake 已设置 `CMAKE_EXPORT_COMPILE_COMMANDS ON`。配置成功后，在构建目录会生成 `compile_commands.json`（例如 `third_party/gfootball_engine/build/compile_commands.json`）。

- **clangd**：在引擎目录可执行 `ln -sf build/compile_commands.json .`（路径按本机 build 目录调整），或在工作区设置 `clangd.arguments` 增加 `--compile-commands-dir=…/build`。
- **勿将** 该文件提交仓库（根目录 `.gitignore` 已忽略引擎根下的 `compile_commands.json` 副本）。
