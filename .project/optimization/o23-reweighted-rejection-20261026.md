# O23 schema6 family-reweighting rejection

## Decision

Reject `reweighted_mean4` for O23 acceptance.  The study completed five fixed
seeds and the independent audit accepted the execution evidence, but the
candidate does not meet the preregistered validation gates.  No confirmation
cases were opened and O24/O25 acceptance work remains ineligible.

## Frozen evidence

- Study: `/root/work_space/football-artifacts/work-o23-reweighted-study-20261021-a/report.json`
  (`d7c748fa3fbc7d0635fb9c00fe42ff5eddbbf6a35ef70f7c1c11253068c5d`).
- Independent audit:
  `/root/work_space/football-artifacts/work-o23-reweighted-study-audit-20261021-a/report.json`.
- Frozen protocol SHA-256:
  `3be05ccca325b22cb4831a77e536634e52b72f8e395df863bf955a35071eebf9`.
- Current source SHA-256:
  `452970a1d260aa599adc8951398ed3e8b8d30127181243dd0c1138da859faa31`.

The audit independently checked 2,000 portable-inference regression episodes,
five full 8,192-update FPPO chains, 655,360 optimizer steps, all 160
checkpoints, native restart reconstruction, and all five exact 8,724-parameter
within-seed means.  It accepted the resource and provenance evidence.

## Gate results

| Requirement | Result | Decision |
| --- | ---: | --- |
| Total validation goals | 952 / 1000 | fail; required at least 970 |
| Every seed | 2026: 173 / 200 | fail; required at least 180 |
| Five geometry families | 190, 200, 194, 185, 183 / 200 | pass |
| Per-seed pass and pass-and-goal counts | all pass | pass |
| Improvement over original legacy baseline | pass | pass |

The other four seeds scored 194, 195, 196, and 194 goals.  The failure is
therefore concentrated in seed 2026 rather than a geometry-wide collapse:
that seed scored 34, 40, 35, 32, and 32 across the five families.  Its pass and
joint counts (171 and 157) remain high, so this evidence does not support a
claim that the reweighting harmed cooperation specifically.

## Consequence and next diagnosis

The schema6 sampling change improved neither the five-seed mean nor the
worst-seed gate enough for release.  This receipt does not authorize lowering
the 970/1000 or 180/200 thresholds, selecting a different averaging window,
reusing the rejected candidate on new confirmation cases, or treating the
prepared O24/O25 tools as accepted work.

The next O23 step is a fresh, versioned diagnosis of the seed-2026
cross-family degradation.  It must derive one new training variable from
training/validation evidence, undergo current-source quality and a bounded
pilot, register a five-seed budget, and use new confirmation cases only after
the validation gates pass.
