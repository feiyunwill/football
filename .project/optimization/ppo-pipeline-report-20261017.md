# PPO pipeline acceptance — 2026-10-17

The bounded end-to-end performance milestone passed: current four-worker PPO
throughput is 2.2102 times single-worker throughput in the registered primary
workload, and the retained spatial cache improves primary pipeline throughput by
a median 9.02%. The other three configuration cost-regression gates passed.
This completes this performance experiment, not the six-to-eight-week learning
and delivery roadmap.

Production source remains
`0058952fa3c56c4506a32cd89744a61d265f85fea8f81af14010736b73448011`.
No additional engine, PPO math, animation, physics or AI changes were made in this
follow-up. Current [quality](../native-training/evidence/spatial-candidate-quality-20261017-b/report.json)
still verifies 74 Python tests and nine C++ contracts, including the spatial
invalidation contract. The [completion audit](../native-training/evidence/pipeline-completion-audit-20261017-b/report.json)
reconciles 80 fixed-workload runs and 822 archived files.

The runner uses the production Python worker pool and collector, and production
C++ categorical PPO math through the existing diagnostic bridge. Every run has
64 real PPO updates, four complete horizon-64 episodes per update, hidden size
16, four epochs, minibatch 64 and base seed 42. Each comparison has eight
independent worker lifetimes per side, alternating AB/BA order. Builds and runs
are serial. Bootstrap intervals use 20,000 draws with seed 42; no slow sample was
removed or replaced. Exact per-update metrics, cumulative replay and complete
weights/Adam/shuffle/version state match within every pair.

The metric is joint environment transitions per measured PPO-loop second; it is
not multiplied by controlled-player count. Collection, callbacks, update math,
diagnostics and in-loop checkpoint/resource sampling are included. Build, worker
startup, warmup, final checkpoint and close are outside the measured loop; these
results are not total command-launch-to-exit speedups or shipped native CLI
benchmarks. Worker exit/reaping and FD restoration are verified separately.

| Comparison/configuration | Median throughput ratio | Paired bootstrap 95% interval | Decision |
|---|---:|---:|---|
| Current four / one worker, 11 players, cadence 2 | 2.210174 | 2.163327–2.258550 | Primary 2× median target passed |
| Current / archived engine, 11 players, cadence 2 | 1.090188 | 1.000450–1.109831 | Positive pipeline-gain gate passed; lower bound close to 1 |
| Current / archived engine, 1 player, cadence 2 | 1.127335 | 1.114528–1.160838 | Median cost ratio 0.887064; ≤1.03 gate passed |
| Current / archived engine, 1 player, cadence 10 | 1.192540 | 1.154531–1.336393 | Median cost ratio 0.838546; ≤1.03 gate passed |
| Current / archived engine, 11 players, cadence 10 | 1.157160 | 0.580367–1.457009 | Median cost ratio 0.864503; ≤1.03 gate passed; positive speedup not established |

The other-configuration gate is the median of paired candidate/baseline costs,
computed directly, rather than the reciprocal of an even-sample median speedup.
The broad 11-player/cadence-10 interval includes substantial regression. The
matrix therefore supports its registered median-cost condition, not a claim that
every configuration or every run is statistically faster. Scaling acceptance
applies to the primary configuration; the other three did not repeat 1/4-worker
scaling. Ratios are specific to this workload and machine.

The archived baseline engine source is `7640b9befe4155bf3887f4f98e20fd056fc4d09127636c0d23da4a28a21fb96a`.
Its module/core hashes and the retained artifacts are bound by the
[primary audit](../native-training/evidence/pipeline-primary-audit-20261017-c/report.json)
and prior [spatial audit](../native-training/evidence/spatial-audit-20261017-b/report.json).
Parent Python/PPO sources stay identical; the runner's current source fingerprint
does not relabel the archived baseline engine as a current-source build.

The parameterization smoke test first exposed a single-player list/scalar action
mismatch in the new runner; it was fixed without changing production APIs.
`pipeline-smoke-20261017-a/failure.json` explicitly records the reconstructed
traceback summary; `pipeline-smoke-20261017-b` passed two updates.

Initial batch `pipeline-primary-20261017-a` was interrupted after observing a
code indexer consuming about 749% CPU. Batch `-b` was rejected by the new
environment gate: index mean 0.290 cores and P95 1.653 cores exceeded 0.25.
Neither batch supplies accepted performance samples. Their protocols, raw runs
and interruption records remain available. A project-local `.cbmignore` excludes
historical evidence source copies and generated diagnostics; the refreshed full
graph has 34,730 nodes instead of 178,415, with current implementation sources
retained. Excluded evidence is read directly when needed.

Accepted batch `-c` and the matrix wrote live artifacts outside the repository,
then archived byte-identical copies after measurement. A read-only one-second
index CPU monitor checks mean and P95 ≤0.25 cores for every run. This bounds
indexer interference, not all possible host scheduling, frequency or external
workload effects. No service, driver, WSL, power policy or global setting changed.

The current-source duration run also completed **1800.021972 seconds, 7,265
updates and 1,859,840 joint transitions**. It observed 1033.23 transitions/s;
minute throughput ranged from 353.29 to 1358.20, with median 1062.64. The last-five
versus first-five minute median ratio was 0.9449. Parent RSS began at 49.12 MiB,
ended at 61.09 MiB and peaked at 62.57 MiB. Worker RSS sum began at 530.85 MiB,
ended at 528.17 MiB and peaked at 530.90 MiB; sums double-count shared pages.
In-run worker FD sum stayed 32; parent FD returned from 5 to 5 after close.
All four workers exited zero and were reaped. A fresh process restored the
complete final learner state and verified frozen inference without changing it.
This diagnostic JSON check is not FPPO resumed-training or learning acceptance.

A different project's concurrent OpenCV compilation was observed during the
duration run and recorded in its [context](../native-training/evidence/current-sustained-context-20261017-a/external-contention.json).
Its processes were not changed. Thus this run verifies duration, finite real
updates, resource observations, checkpoint loading and cleanup under contention;
its throughput is not an isolated stability or speedup proof. No throughput ratio
is computed against the historical 30-minute run.

The [duration analysis](../native-training/evidence/current-sustained-analysis-20261017-a/report.json),
[minute CSV](../native-training/evidence/current-sustained-analysis-20261017-a/minute-costs.csv),
[frozen-load receipt](../native-training/evidence/current-sustained-frozen-20261017-a/report.json)
and [archive manifest](../native-training/evidence/pipeline-archive-20261017-a/manifest.json)
retain the checks and provenance. Matrix evidence is in
`pipeline-matrix-p1-c2-20261017-a`, `pipeline-matrix-p1-c10-20261017-a` and
`pipeline-matrix-p11-c10-20261017-a`, each with a separate audit directory.
Archived original-path receipts remain bound to the source paths recorded in the
manifest; relocation does not rewrite historical reports.

The retained tools are `profile_pipeline_ppo.py`, `benchmark_pipeline_ppo.py`,
`audit_pipeline_ppo.py` and `audit_pipeline_completion.py` under
`.project/native-training/`. Historical runners were preserved. Protocols are
`pipeline-protocol-20261017-c`, `pipeline-matrix-protocol-20261017-a` and
`current-sustained-protocol-20261017-a`. The completion audit can be reproduced:

```sh
/tmp/football-native-training-venv/bin/python \
  .project/native-training/audit_pipeline_completion.py \
  --output /tmp/football-pipeline-completion-review
```

The audit writes a new receipt directory and intentionally refuses to overwrite
an existing one. Preserve the existing receipt before choosing a fresh output
for a repeat. Historical suites and runner copies are archived with their hashes;
the current generalized suite supports explicit protocol/output/work roots.

Remaining roadmap work is an uncontended current-source sustained-throughput
baseline, preregistered varied-start/keeper learning with at least five training
seeds and held-out evaluation, and refreshed isolated install/relocation/train/
resume/frozen-evaluation delivery for this source. Current wheel delivery, remote
CI, GPU acceptance and general football competence were not promoted. See the
[long-term plan](sustained-training-plan-20261017.md).
