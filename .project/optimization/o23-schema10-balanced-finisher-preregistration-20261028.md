# O23 Schema10 balanced-finisher preregistration ¡ª 2026-10-28

## Candidate

One candidate is registered: `2v1_broad_balanced_finisher` (checkpoint payload schema 10). It retains the Schema9 PPO configuration and annealed `.0003` learning-rate schedule, while replacing Schema9's training-only 60% group-4 concentration with the broad sampler's fixed distribution: 20% legacy starts and 16% for each of the five continuous families.

## Rationale and limits

Schema9's rejected frozen evaluation is design-only evidence. Seed 2026 missed goals across groups 0, 2, 3 and 4, and group 2 showed the largest pass-completion shortfall. This candidate tests whether equal continuous-family coverage improves cross-seed stability. It does not claim that sampling caused the failure and does not alter geometry definitions, reward, network, rollout, seed list, or acceptance gates.

## Sequence

1. Add schema-10 isolation, CLI selection, deterministic-sampling and checkpoint incompatibility contracts.
2. Rebuild and complete current-source quality checks.
3. Run one seed-42, 64-update full-versus-32+32 resume pilot within 30 minutes. The pilot may use only holdout diagnostics and cannot use existing O23 frozen cases.
4. If quality, resume identity, resource caps and source identity all pass, register a fresh five-seed resource budget. A later full study must use newly registered independent acceptance cases and unchanged O23 gates: 970/1,000 total goals, 180/200 per seed, 180/200 per group, and 40 completed passes plus 40 joint pass-and-goal episodes per model.

No confirmation, O24 or O25 work is authorized by this registration.
