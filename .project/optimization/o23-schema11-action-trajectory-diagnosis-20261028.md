# O23 Schema11 action-trajectory diagnosis — 2026-10-28

The independently audited action-trace diagnostic replayed the five frozen final policies on the 35 starts where seed 31415 failed while at least three other seeds succeeded. It changed neither source nor models and used no new confirmation cases.

Seed 31415 matched seed 42, 2026, and 271828 on none of the 35 first actions, and matched seed 123 once. Its first action was `release_sprint` 22 times, `bottom_right` 12 times, and `top_right` once. The corresponding peers concentrated on `short_pass` (seeds 42 and 271828), `dribble` (seed 2026), and `right` or `top_right` (seed 123). No observed eight-action prefix was identical between seed 31415 and another seed.

The action-number mapping comes from the immutable native action array: 5 is right, 6 bottom-right, 11 short-pass, 15 release-sprint, and 17 dribble. This establishes a reproducible first-decision policy divergence on the failing starts. It does not establish why the loss landscape produced it, nor does it authorize hard-coding an action or optimizing against these already evaluated cases.

Evidence: `/root/work_space/football-artifacts/work-o23-schema11-action-trace-diagnostic-20261028-a/report.json`; independent audit: `/root/work_space/football-artifacts/work-o23-schema11-action-trace-diagnostic-audit-20261028-a/report.json`.

The next O23 experiment must be a separately preregistered, bounded policy-stability hypothesis that is evaluated on validation data before any new confirmation set. It must retain the frozen 970/1,000, per-seed, group, pass, and joint gates; it may not select or tune an action-specific rule from this trace.
