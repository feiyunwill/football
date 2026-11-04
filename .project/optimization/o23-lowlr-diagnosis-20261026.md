# O23 schema7 low-LR rejection diagnosis

This is a post-rejection description of frozen validation evidence.  It does not select a new model, use confirmation data, or change an acceptance threshold.

The schema7 low-LR mean4 candidate scored 961/1000, nine successes below the fixed 970/1000 total gate.  Seed totals were 193, 195, 195, 194, and 184 for 42, 123, 2026, 31415, and 271828 respectively.

The shortfall is concentrated in seed 271828.  Its five group successes were 34, 40, 39, 36, and 35.  Against the frozen broad80 results in the historical O23 extended study, the low-LR candidate changed per-seed successes by -3, -1, +21, +17, and -6.  It therefore improves the aggregate score over broad80 (961 versus 933) but does not establish the required total robustness.

The group aggregates are 190, 200, 198, 191, and 182, so group coverage is not the failed gate.  Cooperation and legacy-improvement gates also passed.  The only fixed acceptance gate rejected by the study report is the total-success mean gate.

The frozen episode IDs also align for seed 271828.  Against broad80 on those same 200 episodes, the low-LR policy has 10 old-only successes and 4 new-only successes, for the observed net loss of 6.  By group, old-only/new-only counts are 5/0, 0/1, 0/1, 2/1, and 3/1.  The next diagnostic should therefore inspect rollout behavior for seed 271828 groups 0 and 4 before proposing a separately versioned candidate.

All ten old-only successes record zero turnovers under the low-LR rollout.  The five group-0 cases are indices 1, 23, 25, 28, and 37; three of them end in 20--22 steps with zero completed passes, compared with broad80 successes in 33--56 steps.  This is descriptive rollout evidence only and does not justify a score repair or a task-weight change.

The study report carries `known_pilot_prefix_matches=false`, but a direct comparison of the frozen first 64 iteration records is equal.  The independent auditor cannot complete because its frozen source reads the budget directory instead of the frozen `budget/report.json`; changing that source would invalidate the study fingerprint.  These are reporting/auditor defects, distinct from the fixed validation failure.

Required next action: retain the rejection and investigate seed-271828 rollout divergence in a separately versioned diagnostic.  Correct the auditor and summary-flag issues only in a new preregistered run.  Do not reuse confirmation data, lower the 970/1000 gate, change the mean4 window, or open O24/O25.

## Deterministic rollout trace (2026-10-26)

The required rollout comparison is complete.  The production native inference
path replayed both frozen policies against the same 200 registered seed-271828
cases; all 200 episode rows exactly matched the frozen broad80 and low-LR
validation logs.  The trace capture is therefore descriptive only and does not
create a new validation result.

The eight old-only failures in groups 0 and 4 start differently: broad80 chose
action 4 in seven cases and action 6 in one, while low-LR chose action 5 in all
eight.  Across those cases, broad80 averaged 1.599 decision entropy over 320
steps and low-LR averaged 2.418 over 260 steps.  This is a policy-distribution
shift, not evidence that a group-specific reward, case weighting, or acceptance
gate should be changed.  The trace and its parity receipt are retained at
`/root/work_space/football-artifacts/work-o23-lowlr-seed271828-trace-20261026-a/`.

Any successor must be separately versioned and preregister one general
optimization hypothesis before its pilot.  It may not target the observed
groups 0 or 4, reuse the frozen validation cases for selection, or open
confirmation before passing a fresh independent validation.
