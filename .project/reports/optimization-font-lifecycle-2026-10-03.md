# SDL_ttf font lifecycle regression (2026-10-03)

The architecture regression exposed a concurrent GameEnv lifetime failure: LeakSanitizer reported a direct 24-byte allocation and indirect FreeType allocations rooted at TTF_OpenFontIndexRW in engine/src/main.cpp. Game environments can initialize and close fonts on different threads while SDL_ttf initialization and shutdown are process-wide.

The fix serializes TTF_OpenFont/TTF_OpenFontIndexRW, TTF_SetFontOutline, and TTF_CloseFont with the same mutex used for TTF_Init/TTF_Quit. Font file loading stays outside the critical section. This protects the library lifetime without serializing unrelated asset I/O.

Validation:
- Sanitized engine_lifetime_contract: three consecutive runs, each 167 assertions, with ASAN_OPTIONS=halt_on_error=1:detect_leaks=1:quarantine_size_mb=16 and LSAN_OPTIONS=exitcode=23; no sanitizer diagnostics.
- Formal task-20.1.2.2 architecture regression: passed. Receipt: .project/optimization/evidence/architecture_regression.json; raw logs: .project/optimization/evidence/font_lifecycle_regression_20261003.tar.gz; architecture log SHA-256: 271baa54427074576805c578ca340685f3fb349e73bb7996d8eaa6a40cf54465.
- Revalidated dependencies native_boundary, framework_regression, state_ownership, environment_lifetime, and simulation_contract: passed. ms-20.1 reports verified.
- git diff --check and quality.py validate: passed.
