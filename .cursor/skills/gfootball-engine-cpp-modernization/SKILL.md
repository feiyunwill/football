---
name: gfootball-engine-cpp-modernization
description: Guides C++ modernization of gfootball_engine to C++23/C++20, including special member functions (=default/=delete), Boost migration, and RefCounted. Use when upgrading C++, replacing Boost, changing RefCounted, or discussing copy/move constructors, destructors, or six special member functions.
---

# gfootball_engine C++ 现代化

## 目标与范围

- **范围**：仅 `third_party/gfootball_engine`。
- **标准**：C++23 优先，C++20 备选（CMake 中 `CMAKE_CXX_STANDARD 23` 或 20）。

## 当前用法摘要

- **标准**：当前为 C++14。
- **智能指针**：`boost::intrusive_ptr` 为主（RefCounted 基类 + 手写 add_ref/release），refCount 为 `volatile long`（非原子）；少量 `boost::shared_ptr`/`weak_ptr`。
- **其他 Boost**：`boost::bind`/placeholders、`boost::signals2`、`boost::random`、`boost::shared_ptr`。
- **头文件**：`#ifndef _HPP_*` 守卫；可保留或逐步改为 `#pragma once`。
- **验证**：`DO_VALIDATION` 宏（FULL_VALIDATION 时调用 DoValidation）。
- **类型安全**：如 `Observer::subjectPtr` 为 `void*`；后续可考虑 std::any 或类型化接口。

## 六大函数（特殊成员函数）

以下六类：**该禁用的显式 `= delete`，该使用编译器生成的显式 `= default`**。

| 函数 | 建议 |
|------|------|
| 默认构造 | 可默认构造且无额外逻辑 → `= default`；不应默认构造 → `= delete` |
| 拷贝构造 | 不可拷贝 → `= delete`；可拷贝且与编译器一致 → `= default` |
| 移动构造 | 不可移动 → `= delete`；可移动且与编译器一致 → `= default` |
| 析构 | 多态基类必须 `virtual` 并显式实现或 `= default`；其它可 `= default` |
| 拷贝赋值 | 同拷贝构造 |
| 移动赋值 | 同移动构造 |

多态基类务必写 `virtual ~Base() = default;`（或显式实现），避免切片与未定义行为。

## 现代化清单（实施顺序建议）

1. **标准**：CMake 设为 C++23（不支持则 20）。
2. **六大函数**：在新增或修改类时，显式声明并 `= default` / `= delete`；多态基类析构 virtual。
3. **Boost 替换**：新代码用 std；旧代码可逐步将 bind/shared_ptr/random 等替换为 std，注释注明日期与原因。替换时需考虑**性能**（内存、CPU、时间复杂度），**仅当 Boost 在该处无额外优势**（实现、特性或性能上无不可替代收益）时用标准库替代，否则保留 Boost。
4. **RefCounted/intrusive_ptr**：若改动需考虑原子化与 ABI；新模块优先 `std::unique_ptr`/`std::shared_ptr`。
5. **可选**：`std::optional`、`std::variant`、`std::span`（C++20）替代部分可空/多态/裸缓冲区用法；头文件守卫可统一为 `#pragma once`。
6. **数学库**：`src/base/math` 与 `src/base/geometry` 被大量调用，**最大量考虑优化**（inline 热路径、减少拷贝、constexpr、缓存友好、必要时 SIMD；热路径避免堆分配与虚调用）。参见规则 `cpp-math-optimization.mdc`。

## 风格与规范

- **C++ Core Guidelines**：遵循 [C++ Core Guidelines](https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines)（RAII、智能指针、const、接口设计等）。见规则 `cpp-core-guidelines.mdc`。
- **Google C++ Style Guide**：采用 [Google C++ Style Guide](https://google.github.io/styleguide/cppguide.html) 的命名、格式、头文件与注释约定。见规则 `cpp-google-style.mdc`。与现有引擎风格冲突时以本仓库规则为准。

## 修改流程（与 rules 一致）

- 注释掉原代码，注明**日期**与**原因**，再写新代码。
- 不写占位实现；实现需真实可用。
- Git 提交仅在用户明确确认（如「提交 git」）后执行。
