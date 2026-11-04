# O23 Schema11 cross-seed diagnostic — 2026-10-28

## Scope

This is a diagnostic-only analysis of the rejected Schema11 acceptance logs. It performed no training, candidate selection, or confirmation generation. All five models were compared on the same 200 registered starts.

## Findings

Seed 31415 scored 164/200, while the other four scored 189–196. It failed 35 starts on which at least three of the other four seeds succeeded, and succeeded on only three starts on which at least three others failed. The divergent failures occur in every geometry group: group 0 has 11, group 1 has 0, group 2 has 11, group 3 has 7, and group 4 has 6.

The same seed made 523 pass requests and completed 167 passes, versus 734–1123 requests and 191–196 completions for the other seeds. It also ended its episodes sooner on average (43.28 steps versus 48.33–52.90). These are descriptive correlations from an already evaluated set; they do not establish a causal action-selection, reward, or sampler mechanism.

The machine-readable report is `/root/work_space/football-artifacts/work-o23-schema11-cross-seed-diagnosis-20261028-a/report.json`.

## Next gate

Do not implement a group-specific or action-specific change from this analysis alone. The next bounded O23 hypothesis must first include a controlled mechanism test that distinguishes training-seed instability from policy behavior, then use a fresh preregistered 200-case confirmation set if it reaches full-study evaluation. The existing 1,000 Schema11 evaluation episodes remain design data.
