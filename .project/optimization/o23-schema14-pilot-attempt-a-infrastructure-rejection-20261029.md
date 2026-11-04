# O23 Schema14 entropy-high pilot attempt A: infrastructure rejection — 2026-10-29

The attempt at `/root/work_space/football-artifacts/work-o23-schema14-entropy-high-finisher-pilot-20261029-a` is rejected as an **infrastructure-only** result.  It must not be used for a performance, learning, validation, or acceptance claim.

The current-source quality receipt passed before launch:

- Quality receipt: `/root/work_space/football-artifacts/work-o23-schema14-entropy-high-quality-20261029-a/report.json`
- Frozen source SHA-256: `632a0ea078537d8cfe8baa557c9b763b2e56024a6197099a8cb92cdfa26e69de`
- Preregistered candidate: `2v1_broad_entropy_high_finisher` (Schema14, entropy coefficient `0.025`)

`full1024`, `prefix512`, and `resume512` completed, but the required isolated 64-episode holdout-only pilot evaluation did not start.  `pilot-holdout-eval.stderr` contains `Duplicate option`: the runner inherited `--eval-episodes 0` from its shared command and also appended `--eval-episodes 64`.  The CLI rejected that command before any holdout episode was evaluated.  The failed report records approximately 550.22 seconds total elapsed time; its partial work is retained only for diagnosis.

The runner has been corrected so that the common command contains no `--eval-episodes` option.  Training and split/resume commands now explicitly request `0`; the holdout-only command alone requests `64`.

This correction does not alter the candidate, its single preregistered entropy variable, scenario, seed, sampler, rewards, geometry, architecture, inference mode, resource caps, or frozen O23 gates.  A fresh output directory is required for the replacement pilot.  No budget, new acceptance cases, five-seed study, O24, or O25 action is authorized until that fresh pilot and its independent audit pass.
