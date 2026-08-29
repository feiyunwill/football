# Learned Patterns

## 2026-08-29
- **ECS ComponentPool iteration**: Must iterate by entity ID order for cross-platform determinism. Use `for entity_id in sorted(pool.entities)` not `for entity in pool.entities`.
- **Frame sync determinism**: Same seed + same input sequence = identical state hash. Floating point operations must be consistent; avoid `std::unordered_map` iteration.
- **C++23 migration**: Use `std::expected`, `std::optional`, `std::span`, `std::format`. GCC 15.2 (gcc-toolset-15) supports C++23 fully.
- **Build system**: Single-threaded `make -j 1` only. New source files must be added to `sources.cmake`.

## Project Conventions
- Google C++ Style Guide + C++ Core Guidelines
- Types: PascalCase, Functions/vars: snake_case, Constants: kConstantName, Members: trailing underscore
- Six special member functions explicit =default/=delete
- Smart pointers: prefer `std::unique_ptr`/`std::shared_ptr`; `boost::intrusive_ptr` only for RefCounted interop
