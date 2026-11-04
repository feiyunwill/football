# O23 Schema11 deterministic-mechanism diagnostic — 2026-10-28

## Purpose

Schema11 failed because seed 31415 was substantially weaker than the other four training seeds. Before considering a successor, distinguish reproducible seed-conditioned policy behavior from an unobserved runtime source of variation.

## Registered experiment

Run two fresh, serial native PPO jobs with the current quality-verified Schema11 source and exactly the same arguments: scenario `2v1_broad_edge_balanced_finisher`, seed `31415`, hidden size 64, 4 epochs, minibatch 64, rollout 256, cadence 10, episode limit 256, no initial evaluation, zero evaluation episodes, and 1,024 updates. Save and export each run separately.

For each exported policy, replay the already-evaluated Schema11 case file. Compare the two training iteration rows, final checkpoint hashes, exported-policy hashes, and 200 replay rows byte-for-byte. The case file is design data only; these results cannot be used for candidate selection or acceptance.

## Budget and interpretation

Each training process has a 1,800-second wall cap, 512 MiB RSS cap, and 512 MiB total diagnostic-output cap. Runs, exports, and replays are serial. This is a mechanism test, not a candidate pilot or a confirmation. Equal replicas establish reproducibility at 1,024 updates and deterministic policy evaluation; unequal replicas establish an operational nondeterminism investigation. Neither result explains the full 8,192-update seed-quality gap by itself or opens O24/O25.
