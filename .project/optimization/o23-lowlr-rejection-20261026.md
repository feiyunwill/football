# O23 schema7 low-LR study rejection

The preregistered five-seed `2v1_broad_reweighted_lowlr` study completed on 2026-10-26.  Its fixed within-seed mean4 policies were evaluated on the frozen 1,000-episode validation set.

The candidate achieved 961/1000 controlled scoring successes.  The required total gate is 970/1000, so the candidate is rejected.  No confirmation study, O24 stability run, or O25 delivery/replay was opened.

The other fixed gates were satisfied: every seed reached at least 180/200 goals, every group reached at least 180/200 aggregate goals, cooperation reached the fixed pass/joint thresholds, and the legacy-improvement gate passed.  These results do not override the failed total gate.

The five seed goal totals were 193, 195, 195, 194, and 184.  Aggregate group totals were 190, 200, 198, 191, and 182.

Evidence is retained in `/root/work_space/football-artifacts/work-o23-lowlr-study-20261026-a/report.json`.  The frozen independent-audit source resolves the budget receipt as a directory although the protocol freezes `budget/report.json`; it therefore cannot complete without changing a source file that is itself frozen into the study.  Raw first-64 iteration records nevertheless match the pilot; the study report's `known_pilot_prefix_matches` summary flag is stale.  Neither the data nor any acceptance threshold was modified.
