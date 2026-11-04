# O23 Schema12 entropy-stable-finisher preregistration — 2026-10-28

## Hypothesis

Schema11's seed-31415 failure is deterministic and begins with a reproducible first-decision divergence on starts where other seeds succeed. `2v1_broad_entropy_stable_finisher` restores Schema10's broad-balanced sampler (20% legacy starts; the five continuous families retain the original equal exposure) and keeps its annealed learning-rate schedule. It changes only PPO's entropy coefficient from `0.01` to `0.02`.

The hypothesis is that the modest increase in entropy regularization reduces seed-conditioned early action collapse without encoding a preferred action. It does not change rewards, inference mode, policy architecture, action space, geometry, cases, or acceptance gates.

## Compatibility

The variation is checkpoint payload Schema12. Schemas 1–11 retain their existing decoder behavior. Schema12 cannot load another variation's checkpoint, and variation 13 remains invalid.

## Bounded pilot

Run one serial 1,024-update seed-31415 pilot with hidden size 64, four epochs, minibatch 64, rollout 256, cadence 10, episode limit 256, no initial evaluation, and zero training-time evaluation episodes. The training wall cap is 1,800 seconds; RSS is capped at 512 MiB; output is capped at 512 MiB. The pilot must prove current-source quality, Schema12 checkpoint save/load, exported policy integrity, and fixed-case inference completion before a five-seed budget may be registered.

The existing Schema11 cases are design data and may only be used for diagnostic replay. A five-seed Schema12 study requires a new preregistered 200-case confirmation set. The frozen full-study gates remain total 970/1,000, each seed 180/200, each group 180/200, and each model at least 40 pass and joint outcomes. O24 and O25 remain closed.
