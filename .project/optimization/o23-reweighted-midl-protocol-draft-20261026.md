# O23 schema8 candidate draft: reweighted intermediate learning rate

## Evidence and one-variable hypothesis

Schema7 kept the reweighted schema6 sampler but reduced the annealed PPO base
learning rate from `0.0003` to `0.0002`.  It improved the prior broad80 total
from 933 to 961 successes, but was rejected below the fixed 970/1000 gate.
Its frozen seed-271828 trace shows a more diffuse action distribution on the
old-only failures.  That finding does not identify a geometry family, reward,
or validation case to optimize.

Test one general change: use the intermediate base learning rate `0.00025`.
The sampler, rewards, seeds, policy shape, rollout, optimizer, cadence,
episode limit, within-seed mean-four selection, and all acceptance gates remain
unchanged.  The candidate must not select weights, schedules, or cases from
the rejected validation results.

## Frozen candidate definition

- New scenario identity: `2v1_broad_reweighted_midl`; new FPPO payload schema
  is 8 and cannot restore schemas 0--7.
- Learning-rate schedule: `0.00025 * max(0.1, 1 - version / 8192)`.
- Schema6 geometry exposure stays fixed: 20% legacy, 10% each family 0--3,
  and 40% family 4.
- Five fixed training seeds are 42, 123, 2026, 31415, and 271828.  Each uses
  8,192 updates of 256 transitions, hidden width 64, four epochs, minibatch
  64, cadence 10, and an episode limit of 256.
- Inference selection is the equal Binary64 mean of versions 7424, 7680, 7936,
  and 8192.  No other checkpoint or averaging window is eligible.

## Staged gates

1. Current-source quality, schema isolation, a deterministic 64-update versus
   32+32-resume pilot, and independent pilot audit must pass before a full
   study is registered.
2. A registered full study has the same resource limits as schema7: 4,200
   seconds per seed, 21,000 total training seconds, 512 MiB child RSS, and
   2 GiB output.
3. A fresh prospective validation set, generated before full training, is the
   selection gate: at least 970/1000 total successes, every seed at least
   180/200, every geometry family at least 180/200, and per-seed completed
   passes and joint pass-and-score counts at least 40.
4. Confirmation, O24 stability, and O25 delivery remain closed until that
   independent audit passes.  Existing schema7 validation groups remain
   diagnostic evidence only.

## Prospective registration

The pre-training prospective case set was generated with Python PRNG seed
`2026102608` and frozen at
`/root/work_space/football-artifacts/work-o23-midl-prospective-20261026-a/cases.txt`.
It contains 200 unique engine seeds, 40 cases in each of the five geometry
families, and SHA-256
`8776d6a33a869deeda9d22e384962248ab3ef14976a95c67cc29ab4ac8bf570e`.
