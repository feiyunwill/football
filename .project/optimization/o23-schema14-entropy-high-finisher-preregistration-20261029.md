# O23 Schema14 entropy-high-finisher preregistration — 2026-10-29

## Hypothesis

Schema12 (`entropy_coefficient=0.02`) reached 942/1,000 on its own independent set and passed every per-seed gate, while the only lower-entropy successor, Schema13 (`0.015`), fell to 920/1,000, failed a seed, and further weakened geometry group 4. Neither result proves a causal mechanism, and their distinct acceptance sets cannot be pooled. They do support one bounded, global follow-up: `2v1_broad_entropy_high_finisher` changes only PPO entropy regularization from Schema12's `0.02` to `0.025` while retaining its broad-balanced sampler and annealed learning-rate schedule.

The hypothesis is that a modest global increase in entropy regularization improves policy robustness across seeds and the group-wide group-4 weakness without encoding an action, seed, geometry, reward, architecture, inference mode, or acceptance-case preference. This is a single preregistered candidate, not a checkpoint, seed, or inference-mode search.

## Compatibility

Schema14 has its own checkpoint payload and is incompatible with all prior variation payloads. Schemas 1–13 retain their current decoder behavior; variation 15 remains invalid. The named CLI scenario reports an entropy coefficient of `0.025` and retains fixed simple-115 two-on-one policy export eligibility.

## Bounded pilot and gates

Before any five-seed budget or fresh acceptance cases are registered, run one serial 1,024-update seed-31415 pilot with hidden size 64, four epochs, minibatch 64, rollout 256, cadence 10, episode limit 256, no initial evaluation, and zero training-time evaluation episodes. The first training trial is capped at 1,800 seconds, 512 MiB RSS, and 512 MiB output. It must prove current-source quality, Schema14 checkpoint save/load isolation, exported-policy integrity, deterministic split/resume, and fixed-case inference completion.

Only a passing pilot and independently audited budget may register a new 200-case-per-model acceptance set. It must exclude all Schema11, Schema12, and Schema13 acceptance cases and preserve the frozen O23 gates: at least 970/1,000 goals; at least 180/200 per seed and geometry group; and at least 40 completed-pass and joint pass-and-goal episodes per model. O24 and O25 remain closed unless that new five-seed study and its independent audit both pass.
