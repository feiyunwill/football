# O23 schema8 intermediate-learning-rate pilot

Schema8 retains the reweighted broad sampler and changes only the annealed PPO
base learning rate to `0.00025`.  The current-source quality receipt passed
with source fingerprint `7acb9960b08e41f0d8d375172253f241e6bbb0f6a87152899c2a41e0f5b8d239`.

The bounded seed-42 pilot passed all infrastructure gates:

- a 64-update run and a 32+32 resumed run produced byte-identical FPPO
  checkpoints and exported FPOL policies;
- all 64 recorded learning rates followed the registered schedule;
- restoring the schema6 checkpoint was rejected by variation/schema identity;
- the independently reconstructed episode starts matched the completed run;
- the full 64-update run took 17.648 seconds, projecting 2,258.931 seconds
  for 8,192 updates, inside the 4,200-second per-seed study limit.

The independent audit passed.  This pilot contains no validation or
confirmation episodes and makes no learning claim.  The next gate is to
register a new prospective validation set before the five-seed full study.
