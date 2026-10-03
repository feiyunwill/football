# Tactical scenario coverage in the input gate (2026-10-03)

Scope: ms-22.1 / plan-22.1.1 / task-22.1.1.1.

The input acceptance gate failed before input-specific tests because its tactical-state subcheck required exactly 27,618 assertions, 3,513 nonzero controlled actors, and 325 set-piece frames. The recent AI mirror correction changed the match trajectory. The current contract still passes its own observation assertions and reports 27,450 assertions, 3,588 nonzero controlled actors, and 98 set-piece frames in both Release and ASan/UBSan builds. Exact historical trajectory totals are not invariant input-sampling requirements.

The native tactical contract now reports actor and set-piece coverage for each of four seed/physics scenarios and requires at least 720 nonzero controlled-actor observations per 240-frame scenario. Both full-physics scenarios must exercise a set piece. The Python acceptance checker validates the complete scenario matrix, aggregate totals, and exact Release/Sanitizer parity, while retaining a 27,000-assertion floor and the existing 960 actual GameEnv frames. It no longer accepts a padded global count in place of scenario coverage.

Independent Release and sanitized runs each passed 27,456 assertions. Per-scenario nonzero actors were 960, 876, 960, and 792; set-piece frames were 0, 4, 0, and 94. The two builds produced identical reports. The targeted acceptance unit tests, quality.py validate, and git diff --check pass. Full task acceptance is pending.
