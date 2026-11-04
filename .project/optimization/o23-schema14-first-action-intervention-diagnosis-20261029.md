# O23 Schema14 first-action intervention diagnosis — 2026-10-29

The pre-registered Schema14 first-action intervention diagnosis and its independent audit both passed.

- Preregistration: `o23-schema14-first-action-intervention-preregistration-20261029.md`
- Diagnostic receipt: `/root/work_space/football-artifacts/work-o23-schema14-first-action-intervention-diagnosis-20261029-a/report.json`
- Diagnostic SHA-256: `4626fd7af8e54258963e157f449793834ac2222ac7f6c05f689f16be6390b4dd`
- Independent audit: `/root/work_space/football-artifacts/work-o23-schema14-first-action-intervention-diagnosis-audit-20261029-a/report.json`
- Audit SHA-256: `97e0d8d7d53bb07c920de13c948b6f0d53bd9a09ad380bc261f602b8e9d02aed`

The test used the 11 cases that failed under all five Schema14 policies (55 fixed seed–case pairs).  Every baseline exactly reproduced its original non-goal result and completed-pass count.  On a separate deterministic reset, the helper consumed the policy's first random decision, replaced only the applied first action, then resumed the same controller state and policy continuation.

H14-C1 was not falsified: outcome was not invariant to the first action.  In particular, forcing action 12 produced goals for 11, 10, 10, 10, and 10 of the 11 cases for seeds 42, 123, 2026, 31415, and 271828 respectively.  The complete 19-action table is in the machine-readable receipt.

This is a local counterfactual result, not an accepted policy improvement.  It does not establish that action 12 should be hard-coded, that it is optimal outside these cases, or that changing a reward, entropy, sampler, architecture, or inference setting will reproduce the effect.  Schema14 remains rejected; confirmation, O24, and O25 remain closed.

The next permissible step is a separately preregistered trainable policy-distribution hypothesis with an explicit mechanism, control, prediction, stop condition, capped pilot, and new independent acceptance cases.  It must not select on or accept against Schema14 cases, and all frozen O23 gates remain unchanged.
