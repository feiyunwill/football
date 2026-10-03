# Current-gameplay ECS reference after AI mirror correction (2026-10-03)

Scope: ms-21.1 / plan-21.1.1 / task-21.1.1.1 and task-21.1.1.2.

The previous frozen ECS v7 binary predates the AI mirror and UDP ready-barrier corrections. Its warmup hash differs from the current candidate, so the old comparison stops before the performance cohort. This is a workload mismatch, not evidence of a performance regression.

Versioned ECS v8 was built from source commit 7808eae in an isolated worktree. The recorded rollback patch changes only vector3.hpp, humanoid.cpp, humanoidbase.cpp, and humanoidbase.hpp, reversing distance and animation-selection-buffer optimizations while retaining current gameplay. The manifest pins the patch, generator, sources, compiler, evidence, and binaries by SHA-256. For seeds 42 and 43, two reference runs and a candidate run have equal warmup, checkpoints, final hashes, and active flags. The 122-assertion relocated baseline preflight passes.

The diagnostic RunPlayerSystems interposer records zero calls in both builds because the system is invoked through an internal callback. The full-frame, physics-sync, collision-cache, and full-cache wrappers run on both sides; identical wrapper coverage and lower full-frame allocation count and bytes remain mandatory. Unit tests cover symmetric zero calls, missing active wrappers, and baseline hash validation.

The fixed 15-pair-per-seed formal comparison passed 1,590,027 assertions with no skipped cases or failures. Candidate/reference CPU geometric ratios are 0.7891 (seed 42) and 0.8183 (seed 43), with deterministic bootstrap 95% upper bounds 0.8334 and 0.8404. Wall-time geometric ratios are 0.7890 and 0.8182; median paired p99 ratios are 0.7331 and 0.7583. Frame allocation counts decline 1,999,338 to 1,823,608 and 2,180,977 to 1,996,791; bytes decline 132,615,731 to 113,747,811 and 144,718,401 to 124,957,785. Inputs and every trajectory checkpoint match within each pair.

Current-match raw evidence: .project/optimization/evidence/match_ai_mirror_current_20261003.json.gz.
Formal paired raw evidence: .project/optimization/evidence/ecs_v8_passed_formal_20261003.json.gz.
Frozen reference and preflight: .project/optimization/baselines/ecs_v8.json and referenced artifacts.
After commit 954ca37, quality.py run task-21.1.1.2 passed all dependencies and the formal ECS check. plan-21.1.1 is verified. The current receipts, logs, and raw quality-run artifacts are archived at .project/optimization/evidence/ecs_v8_quality_receipts_20261003.tar.gz.
