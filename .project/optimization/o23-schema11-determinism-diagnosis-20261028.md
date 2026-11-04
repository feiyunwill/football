# O23 Schema11 deterministic-mechanism diagnosis — 2026-10-28

Two fresh, serial 1,024-update runs used the same Schema11 source, seed 31415, training configuration, and frozen engine build. An independent audit confirmed that checkpoint hashes, exported policy hashes, all 1,024 training rows, and all 200 replay rows were byte-identical. The two training jobs took 277.612 and 282.072 seconds with peak RSS below 80 MiB.

This rules out unobserved runtime variation in the registered short-prefix training and in fixed-policy evaluation. It does not prove that the full 8,192-update seed gap is caused by any particular PPO parameter, sampler group, or action. The short diagnostic therefore does not authorize a candidate change.

The evidence is at `/root/work_space/football-artifacts/work-o23-schema11-determinism-diagnostic-20261028-a/report.json`; its independent audit is at `/root/work_space/football-artifacts/work-o23-schema11-determinism-diagnostic-audit-20261028-a/report.json`.

The next controlled mechanism test must inspect action trajectories of the existing final policies on already-evaluated divergent starts. It must be source-independent, use no new confirmation cases, and distinguish fewer pass attempts from other early policy divergences before a new candidate is preregistered.
