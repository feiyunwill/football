# O23 Schema11 edge-balanced-finisher — final rejection

## Decision

The independently audited five-seed Schema11 study is rejected. It completed without an operational failure, but did not meet the frozen O23 acceptance gate. O24 and O25 remain closed.

## Evidence

The study used the preregistered `2v1_broad_edge_balanced_finisher` sampler and five fixed seeds. It retained the quality-verified source identity `c9bb08213e3fbca1e4b9baeb98af8115ef49aae95a5226a0350aa60b63e87b0e`, completed every 8,192-update training run, reconstructed every native start, and passed 2,000 historical portable-regression episodes.

The newly registered 200-case set was evaluated by each model (1,000 episodes total). Goals were 937/1,000, below the frozen 970/1,000 mean gate. Seed 31415 scored 164/200, below the 180/200 per-seed gate. Group totals were 182, 199, 185, 189, and 182, so the five geometry-group gates passed. Every model also met its pass and joint-cooperation gates.

The study report is `/root/work_space/football-artifacts/work-o23-schema11-edge-balanced-finisher-study-20261028-b/report.json`. The independent audit is `/root/work_space/football-artifacts/work-o23-schema11-edge-balanced-finisher-study-audit-20261028-a/report.json`; it passed as an audit while correctly reporting `validation_passed: false`.

## Consequence

This result is immutable failure evidence. The 1,000 evaluated episodes are now design data and cannot be reused as confirmation for a future candidate. Any follow-up must be a separately versioned, bounded O23 validation candidate with a new preregistered 200-case confirmation set, current-source quality evidence, a short recovery-audited pilot, and a registered five-seed budget. It must retain the 970/1,000, per-seed, group, pass, and joint gates.

The immediate research target is cross-seed stability: the Schema11 group-4 reweighting eliminated neither the low group totals nor the seed-31415 collapse. A new candidate should be selected only after a diagnostic explains this instability; no scenario-specific repair may be chosen from the held-out confirmation cases.
