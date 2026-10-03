# Current-gameplay long-match reference after AI mirror correction (2026-10-03)

Scope: ms-21.1 / plan-21.1.2 / task-21.1.2.2.

The previous soak v5 reference used the ECS v7 engine from before the recent AI mirror correction. The current candidate's warmup hash differs, so performance_regression stopped before evaluating its five budget requirements. The stopped seed-42 run independently passes all five requirements; the failure is a reference workload mismatch.

Soak v6 reuses the immutable soak v2 benchmark workload binary and the ECS v8 pre-optimization reference engine. Both binaries are checked against their repository manifests and loader linkage. Its generator validates 36,000 measured frames for each seed, compares complete input, warmup, checkpoint, final-state, and activity trajectories against the current candidate, and requires the original five budget thresholds for both versions. The v6 manifest pins the parent, ECS source, generator, raw runs, validation logs, and binaries by SHA-256.

Seed 42: candidate p99 6.711 ms, reference p99 10.351 ms, observed candidate RSS growth 73,728 bytes. Seed 43: candidate p99 6.994 ms, reference p99 10.015 ms, observed candidate RSS growth 73,728 bytes. Both candidates pass all five requirements and match the frozen reference trajectory. The validation archive is .project/optimization/evidence/soak_v6_validation_20261003.tar.gz; the manifest is .project/optimization/baselines/soak_v6.json.

The checker and declared quality sources now point to soak v6. quality.py validate and 20 soak unit tests pass. After commit 536fd0d, quality.py run task-21.1.2.2 passed the full dependency chain; ms-21.1 is verified. Formal seed-42/43 p99 values are 8.413/9.196 ms, observed RSS growth is 73,728 bytes for each, and all five long-match requirements pass. Current receipts, raw logs, compiler identity, and artifacts are archived at .project/optimization/evidence/soak_v6_quality_receipts_20261003.tar.gz.
