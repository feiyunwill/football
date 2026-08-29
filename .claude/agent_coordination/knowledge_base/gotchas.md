# Gotchas & Pitfalls

## 2026-08-29
- **Constants duplication**: `gfootball/frame_sync/config.py` and `src/frame_sync/protocol.hpp` MUST stay in sync. Change both when modifying protocol constants.
- **ECS iteration order**: ComponentPool uses vector indexed by entity ID. Removing mid-iteration invalidates indices. Use swap-and-pop + update entity ID mapping.
- **Headless rendering**: Server uses `MockRenderer3D` (no GPU/window). Don't call SDL/OpenGL functions in server code paths.
- **Python env**: Must use `~/.local/bin/python3.11` (the .so was compiled against it). PYTHONPATH must include repo root for imports.
- **Single-threaded build**: Parallel `make` causes race conditions in generated files. Always `make -j 1`.
- **RL training**: Uses `gfootball_engine` as pybind11 module. Changes to `ai.cpp` bindings require rebuild + reinstall.
