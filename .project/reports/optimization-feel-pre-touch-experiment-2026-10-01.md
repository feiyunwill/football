# Pre-touch manual steering experiment (2026-10-01)

This branch isolates three manual-direction interventions in `Humanoid::Process` and `SelectAnim`: momentum recovery during a movement animation, movement requeue after a committed ball touch, and a bounded trajectory offset before a pending BallControl/Trap touch. The pre-touch offset is limited by predicted contact distance and saved in the existing animation state.

The engine and native window trace built successfully. The real product-window/XTEST seed-56 focused run admitted 4 presses and observed velocity responses for 3. One press had no qualifying response; the slowest observed response was 200.892 ms. The benchmark's technical `passed` field is true, but `acceptance_passed` is false. The exact JSON report is versioned at `.project/optimization/benchmarks/feel-pre-touch-steer-seed56-20261001/report.json`.

This is an experiment, not a product-quality acceptance result. Keep it off `master` until touch continuity, deterministic replay, and the formal 60-press feel gate pass.
