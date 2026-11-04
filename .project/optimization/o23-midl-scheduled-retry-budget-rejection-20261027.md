# O23 schema8 scheduled successor budget rejection

The corrected scheduled-study successor did not produce a candidate result.
Its schema8 start helper argument was corrected, but seed `42` was terminated
while producing the `7,936` checkpoint by the unchanged 2,520-second
per-seed wall-clock guard.

The report records 2,519.402 training seconds, ten matching historical
portable regressions, completed checkpoints through 7,680 updates, and peak
child RSS below 512 MiB.  The terminated child produced neither a checkpoint
nor an iteration log.  No validation, confirmation, stability, or delivery
stage was opened.

This preserves the limit rather than retroactively expanding it.  The earlier
scheduled run contains a complete, within-budget seed-42 training chain: all
11 checkpoints through 8,192 updates in 2,470.475 training seconds.  Its
later failure was the independently fixed schema argument supplied only to
the non-training start-reconstruction helper.  Any recovery must freeze and
independently verify that completed chain, retain both failed reports, and run
the remaining fixed seeds serially under the same registered budget.

Evidence is retained at
`/root/work_space/football-artifacts/work-o23-midl-scheduled-study-20261027-c/report.json`.
