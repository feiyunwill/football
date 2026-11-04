# O23 Schema13 entropy-midpoint-finisher preregistration — 2026-10-29

## Hypothesis

Schema12 completed deterministically but missed its frozen aggregate and group-4 gates. Its audited action trace shows group-wide weakness and seed-dependent first-decision divergence without establishing an action-specific causal repair. `2v1_broad_entropy_midpoint_finisher` retains Schema12's broad-balanced sampler and annealed learning-rate schedule. It changes only PPO entropy regularization from `0.02` to `0.015`, the fixed midpoint between the original `0.01` and Schema12's `0.02`.

The hypothesis is that an intermediate global entropy coefficient balances seed-conditioned policy concentration and divergence without action, group, seed, geometry, reward, architecture, inference, or acceptance-case targeting.

## Compatibility

The variation is checkpoint payload Schema13. Schemas 1–12 retain existing decoder behavior. Schema13 cannot load a checkpoint for another variation, and variation 14 remains invalid.

## Bounded pilot

Run one serial 1,024-update seed-31415 pilot with hidden size 64, four epochs, minibatch 64, rollout 256, cadence 10, episode limit 256, no initial evaluation, and zero training-time evaluation episodes. The training wall cap is 1,800 seconds; RSS is capped at 512 MiB; output is capped at 512 MiB. The pilot must prove current-source quality, Schema13 checkpoint save/load, exported-policy integrity, deterministic split/resume, and fixed-case inference completion before registering a five-seed budget.

Schema11 and Schema12 acceptance data are design-only and cannot be reused for Schema13 selection or acceptance. Any Schema13 five-seed study requires a new preregistered 200-case set. Frozen O23 gates remain total 970/1,000, each seed 180/200, each group 180/200, and at least 40 completed-pass and joint pass-and-goal episodes per model. O24 and O25 remain closed.
