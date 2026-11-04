# O23 Schema11 edge-balanced-finisher preregistration — 2026-10-28

## Candidate

`2v1_broad_edge_balanced_finisher` uses checkpoint payload schema 11. It keeps the Schema10 PPO settings and annealed learning-rate schedule. Its training sampler remains 20% legacy starts, raises continuous group 4 from 16% to 20%, and assigns each remaining continuous group 15%.

Schema10's preregistered independent study scored 967/1000 against its fixed 970-goal gate. All seed, group, pass, and joint gates passed, while group 4 was the lowest cross-model group at 189/200. Schema9's 60% group-4 concentration was rejected, so Schema11 tests only this bounded reweighting.

## Rules

Schema10 models, study output, cases, and failed audit attempts remain immutable evidence. Schema11 starts from new training only; schema9 and schema10 checkpoints are intentionally rejected. The pilot is limited to 64 updates and 30 minutes. A full five-seed study may begin only after current-source quality checks, pilot recovery audit, a recorded budget, and a newly generated 200-case acceptance set all pass.

The full-study gates remain frozen at total 970/1000, every seed 180/200, every geometry group 180/200, and each model's pass and joint counts at least 40. This document does not open O24 or O25.
