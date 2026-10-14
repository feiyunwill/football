# 构建、安装与 ABI 范围

2026-10-15。以任务原始日志为准；“允许安装”不等于“已经验收”。

| 平台 / Python | 本路线验证状态 | 限制 |
|---|---|---|
| Linux/WSL x86_64，glibc2.44，GCC16.1.1，CPython3.14.7 | NT-5.2 干净提交源码 PEP517 wheel、全新 venv 安装 probe、原生包迁移及真实训练/续训/冻结评估实测；完整安装后 suite 见最终任务报告 | wheel 为 cp314-cp314-linux_x86_64，依赖该 host 兼容系统库 |
| Ubuntu GitHub runner，GCC15，CPython3.11 | NT-5.1 已配置独立 CI 作业；尚无本轮远端运行结果 | 本地 3.14 结果不作为 3.11 已通过证据 |
| CPython3.10、3.12、3.13 | requires-python>=3.10 允许；本路线未逐版本构建/安装 | 必须为对应 Python minor 重新构建并运行门禁 |
| Windows | 既有工程支持 MSVC/vcpkg 和 native MinGW 配置；新训练链路未在本路线实际构建/安装 | Linux wheel/目录包不可使用；新训练程序、合约和资源加载不列为已验收 Windows 能力 |
| macOS | 既有 Darwin wheel/CMake 分支存在；本路线没有 macOS runner 的实际验证 | Linux ELF/RUNPATH 与目录包不适用，需验证 dylib/loader_path、资源和依赖 |

当前 wheel 不是 abi3、pure-Python 或 manylinux 发布；只声称当前 CPython ABI
与 Linux host 的实际安装。原生程序自身没有 Python 链接依赖，仍使用系统 SDL2、
OpenGL/EGL、libc/libstdc++ 等动态库；不承诺跨 Linux distribution 或 CPU ABI。
目录迁移要求整体搬移 bin/core/data/fonts，不等于跨 ABI 发布。

FPPO、FTRN 和底层 simulation snapshot 校验来源/构建/资源身份；checkpoint
恢复要求同源、相同构建与配置，不能用版本号相同推断跨 Python/C++ build 或平台
兼容。迁移验证中的完整训练与续训来自同一交付产物，资源来自实际安装/目录包。

构建可使用 Python 编排和 PEP517；原生运行入口由 shell 直接 exec C++，无需
Python interpreter。Windows/macOS 和更多 CPython 版本若成为需求，需要补齐
该平台实际构建、安装、资源、恢复和质量门禁证据之后再更新本表。
