# Final-source learning and delivery target — 2026-10-18

Complete the agreed next target: a real PPO policy that improves on untrained and
uniform-random policies at previously unseen shooting starts, with results
reproducible from the current-source installation/package. Complete a final-source
30-minute run with no observed foreign compiler and bounded observed foreign WSL
CPU load. Keep the earlier performance receipts bound to their historical source.

Initial greedy-trial implementation source was
`98f93f0946a5a83e9549c0ef348786b51a1827ca05ab365ba1cc786f3d2db06b`.
[Full quality](../native-training/evidence/generalization-quality-20261018-b/report.json)
passes76 Python integration tests and9 C++ contracts. Added contracts cover all12
starts in three disjoint geometry partitions, deterministic sampling, real
cross-episode resumed updates and rejection of wrong-scenario checkpoints.
Fixed scenarios keep their existing payload schema; variable scenarios have an
explicit inner schema2 and variation identifier. Ownership, lifecycle, resource,
checksum and atomic-restore checks remain in force.

The registered study is `../native-training/validate_generalization.py`; exact
protocol/tool/source/binary hashes are written before training to
`/tmp/football-generalization-study-20261018-b/evidence/`.

| Task | Defender | Mean success minimum | Per-training-seed minimum |
|---|---|---:|---:|
| varied_empty_goal | Lazy goalkeeper parked at normalized(1,.6), outside shot area | .70 | .50 |
| varied_keeper | Normal engine AI goalkeeper at(1,0) | .20 | .10 |

Each task selects sparse64 or checkpoints64 using only one pilot training seed7,
390 updates/configuration, and32 validation episodes with seed77173. Selection is
frozen for both tasks before any test episode. Final training uses seeds42,123,
2026,31415,271828 independently,780 updates ×256 transitions, hidden64, cadence10,
episode horizon256, four PPO epochs and minibatch64. No weights are silently
transferred across incompatible scenario checkpoints.

Training starts form a4×3 grid: player x=.68+.05*i, y=-.10+.10*j and ball x=.02
ahead. Validation adds(.0125,.0125), test adds(.025,.025), so exact starting
geometries are disjoint. These are bounded normalized shooting starts, not a
claim of arbitrary-location or11v11 generalization.

Every final seed receives200 held-out episodes:50 for each evaluation seed600001
through600004. All strategies share engine seed/start identity. Success requires
actual positive controlled-score delta before horizon; truncations remain
failures. Evaluation verifies unchanged complete learner bytes. Both task gates
require the table thresholds, each final seed beating its own untrained and
random baseline, and positive lower95% bounds against both baselines using10,000
crossed training-seed/shared-episode bootstrap draws. Execution success and
learning success are separate fields. Preserve failures and do not tune on test
results or drop unsuccessful seeds.

Prototype study-a was interrupted to correct task fidelity: its stationary
goalkeeper was still in the shot area. Zero held-out logs existed at correction;
the corrected study-b re-registers both tasks and reuses no prototype scores.
The preliminary duration run-a was also interrupted intentionally to put the
long-run baseline after final source changes; it is not accepted duration data.

After the study, run `profile_quiet_ppo.py` for at least1800 seconds against this
source/quality. Its ten-second preflight and one-second monitoring require no
observed foreign compiler and mean/P95 foreign and index CPU each≤.25 cores.
It excludes the wrapper and descendants, records the monitoring limits, and
gracefully rejects a run if a competing compiler appears. Check minute costs,
resources, complete frozen checkpoint and worker/FD cleanup. Do not change other
projects or system power/driver/WSL settings to obtain a result.

`validate_current_delivery.py` uses `snapshot_current.py` to create an exact
working-tree tar, including modified and new build inputs and actual runtime
resources. It does not mutate Git history/index or pretend HEAD contains these
changes. It builds a real wheel, installs to a new venv, tests from outside the
repository, relocates the native bundle, and verifies actual full/resumed
training and frozen evaluation. Finally verify learned checkpoints/results using
the delivered native program; preserve build/ABI rejection instead of loosening
compatibility checks. Record all provenance and reproduction commands.

Only mark the target complete after learning, final-source low-contention run and
current-source installation/reproduction all pass. Publishing, remote CI, GPU,
other platforms and full football competence are outside this target.


## Confirmation revision c

Greedy trial b was rejected: seed31415 had0% argmax test success versus47%
untrained. Its sampled training returns were high; a validation-only frozen
check on seed77173 showed96.875% sampled success and0% argmax. This diagnosed a
deployment-mode mismatch, not a zero-update/restore failure. All old observations
remain; no seed was replaced or promoted after failure.

`validate_sampling_generalization.py` registers a NEW confirmatory trial before
fresh training/evaluation. The primary policy is categorical sampling; greedy
results remain in full raw evaluations and per-batch secondary metrics. All
score/seed/CI thresholds, training seeds, pilot and final training budgets remain
unchanged. Validation chooses only sparse64 versus checkpoints64. Final models
are newly trained against the new source/build identity; no old checkpoint
compatibility guard is bypassed.

The new `confirmation` partition offsets training starts by(.0375,.0375), is
disjoint from all three earlier geometry sets, and uses fresh engine evaluation
seeds700001 through700004. The complete confirmation episodes with these seeds remain unopened until registration and training; geometry/short-step contracts use separate fixture seeds.
The current source/quality and immutable protocol are recorded by the c receipts.
Actual installation replay must reproduce the sampled-policy decisions, while
preserving all secondary argmax outcomes. Passing this trial will make no greedy
policy or arbitrary-location/11v11 claim.

Confirmation source: `9443b0308bd536d70df6cd567177fa17d3db071269b6f3becd84d9a404334029`. [Current full quality](../native-training/evidence/generalization-quality-20261018-c/report.json) passes76 Python tests and9 C++ contracts. Current protocol/raw results are under `/tmp/football-generalization-study-20261018-c/evidence/`.

2026-10-18：约定的学习泛化、当前源码 30 分钟运行与安装后模型复现目标已完成，见 [最终报告](generalization-delivery-report-20261018.md).
