# O23 Schema14 entropy-high-finisher final rejection — 2026-10-29

Schema14 completed its bounded five-seed study and the independent audit completed successfully.  The execution and audit receipts establish deterministic checkpoint/resume behavior, frozen source/case integrity, serial resource compliance, and valid inference on the new independent case set.  They do **not** establish O23 acceptance.

- Study: `/root/work_space/football-artifacts/work-o23-schema14-entropy-high-finisher-study-20261029-a/report.json`
- Independent audit: `/root/work_space/football-artifacts/work-o23-schema14-entropy-high-finisher-study-audit-20261029-a/report.json`
- Terminal supervisor receipt: `/root/work_space/football-artifacts/work-o23-schema14-entropy-high-finisher-study-supervisor-20261029-a.json`
- Frozen independent cases: `fca3266b063d9f9eedc92f62f9564f6d9b5ed08d0d078cac2d7d4a10b42ebc59`

The candidate scored 923/1000 goals (92.3%).  This is below both the frozen O23 total gate of 970/1000 and the roadmap target of 93%.  All five seeds met the 180/200 per-seed gate and all completed-pass/joint gates, but those successes cannot compensate for a failed aggregate gate.

The group totals were `[174, 200, 194, 190, 165]` out of 200.  Groups 0 and 4 are below the frozen 180/200 group gate.  Per-seed goal/pass/joint counts were:

| Seed | Goals | Passes | Joint |
| --- | ---: | ---: | ---: |
| 42 | 185 | 189 | 182 |
| 123 | 184 | 189 | 182 |
| 2026 | 184 | 188 | 181 |
| 31415 | 185 | 186 | 180 |
| 271828 | 185 | 186 | 180 |

Schema14 is therefore rejected independently under the pre-registered gates.  Confirmation, O24 stability work, and O25 installation/replay work remain closed.  The next allowed action is a separately preregistered, bounded diagnosis of the aggregate and group failures; it must not reuse this candidate's acceptance cases, relax gates, or infer an action-specific repair without causal evidence.
