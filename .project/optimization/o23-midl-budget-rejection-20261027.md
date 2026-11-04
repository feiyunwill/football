# O23 schema8 intermediate-learning-rate budget rejection

The registered schema8 full study was started only after its ten historical
portable-regression replays passed.  It did not produce a candidate result.

The first training seed (`42`) completed 25 checkpointed 256-update chunks
(6,400 updates), then the `6,656` chunk was terminated by the registered
per-seed wall-clock guard.  The study report records 2,518.170 training
seconds against the fixed 2,520-second limit.  The terminating child received
SIGTERM after 49.429 seconds; it did not emit a checkpoint or training log.

This is a budget rejection, not a learning or validation result.  All ten
historical replays matched their archived logs, child RSS peaked at
134,230,016 bytes (below the 512 MiB limit), and the frozen engine source hash
was unchanged throughout the run.  No confirmation, stability, or delivery
stage was opened.

Evidence is retained at
`/root/work_space/football-artifacts/work-o23-midl-study-20261027-a/report.json`.
The registered budget is not changed retroactively.  Any successor must be
separately versioned and preregistered, demonstrate exact checkpoint/resume
equivalence under its own operational schedule, pass a bounded pilot and
independent audit, and retain the existing acceptance gates.
