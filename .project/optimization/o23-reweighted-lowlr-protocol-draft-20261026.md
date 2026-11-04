# O23 candidate draft: reweighted low learning rate

## Evidence and hypothesis

Schema6 reweighting was independently valid but rejected at 952/1000.  The
only failed seed was 2026 (173/200), and its failures were distributed across
all five held-out geometry families.  Its observed family exposure was close
to the other seeds, so another family-weight adjustment is not evidence-led.
Its maximum pre-clipping gradient norm (4.616459) exceeded the other seeds'
3.677413--4.040791 range.  Test one variable: reduce PPO base learning rate
from `0.0003` to `0.0002`, retaining the existing annealing multiplier.

## Frozen candidate definition

- New scenario identity and FPPO payload schema: `2v1_broad_reweighted_lowlr`.
- Same schema6 geometry sampler (20% legacy, 10% families 0--3, 40% family 4),
  rewards, 115-feature/64-hidden policy, seed list, rollout 256, 4 epochs,
  minibatch 64, cadence 10, and 8,192 updates.
- Learning-rate schedule: `0.0002 * max(0.1, 1 - version / 8192)`.
- Fixed inference selection: equal Binary64 mean of exports at 7424, 7680,
  7936, and 8192 for each seed.  No alternate window is permitted.
- FPPO checkpoints from schemas 0--6 and schema7 must not cross-restore.

## Sequence and gates

First run an isolated 64-update pilot, including full64 versus 32+32 resume
equality.  The pilot has a hard 30-minute wall cap.  Only a source-fingerprint
quality receipt, schema isolation, deterministic pilot, and registered
five-seed budget permit the later serial full study.  Its old-validation gate
remains 970/1000, every seed at least 180/200, each family at least 180/200,
and per-seed pass and joint counts at least 40.  New confirmation data may be
created only after those validation gates pass; confirmation, O24, and O25
retain their existing stricter acceptance requirements.
