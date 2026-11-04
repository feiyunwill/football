# O23 schema8 scheduled-study helper rejection

The separately registered scheduled-checkpoint study completed all 8,192
updates for its first training seed (`42`) within the registered per-seed
training budget, but did not produce a candidate result.

After the final checkpoint, the frozen start-reconstruction helper was invoked
as `starts 7 42 40507`.  That helper is explicitly schema8-only and rejects a
variation value other than `8`; it exited with code 1 and wrote `Invalid
reconstruction budget`.  The study runner supplied the stale schema7 value.

This is a runner/protocol defect, not a learning or validation result.  The
report records 2,470.475 training seconds for seed 42, all 11 checkpoints up
to 8,192 updates, ten matching historical portable regressions, and peak
training RSS below the registered 512 MiB cap.  No model was accepted, no
prospective confirmation was evaluated, and O24/O25 remain closed.

Evidence is retained at
`/root/work_space/football-artifacts/work-o23-midl-scheduled-study-20261027-b/report.json`.
The existing budget remains unchanged.  A successor must freeze a corrected
schema8 runner, re-run the serial five-seed study from scratch, and satisfy
the original gates under independent audit.
