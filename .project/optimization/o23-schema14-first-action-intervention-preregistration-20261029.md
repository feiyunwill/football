# O23 Schema14 first-action intervention diagnosis preregistration — 2026-10-29

## Status and boundary

Schema14 was independently rejected under frozen O23 acceptance gates.  This is a bounded causal **diagnostic** on its already-evaluated data, not a successor experiment, confirmation, acceptance result, or authorization for O24/O25.  The 200 Schema14 cases are design-only and cannot be used for acceptance.

## Falsifiable hypothesis

**H14-C1:** for at least one of the 11 cases that failed under every Schema14 seed, outcome is not invariant to the first controlled action when all scenario inputs, model weights, action-random stream consumption, and policy continuation are held fixed.

The hypothesis is falsified if every forced first action (0–18) yields the same non-goal outcome as the matched policy-action baseline on all 55 seed–case pairs.  A detected effect establishes only a local counterfactual action effect; it does not identify a trainable repair, justify hard-coding an action, or select a successor.

## Intervention and controls

- Cases: only universal failures from the immutable Schema14 diagnosis: indices `14, 17, 25, 127, 152, 163, 173, 175, 191, 193, 194`.
- Seeds/policies: final Schema14 policies for `42, 123, 2026, 31415, 271828`, executed serially.
- Baseline: run the sampled policy first action and its normal continuation.
- Treatment: on a separate reset of the identical case, consume the sampled policy decision exactly once, replace only the applied first action with each action `0..18`, then continue with the same policy/controller state.
- Invariant inputs: case geometry, engine seed, action seed, model file, horizon, policy continuation, and source/build fingerprint.
- Required control: each baseline's goal/non-goal and completed-pass count must exactly reproduce the corresponding frozen study log before its intervention rows are accepted.
- Output: 20 episodes per seed–case (one baseline plus 19 treatments), or 1,100 episodes total.  No training or evaluation job may run concurrently.

## Decision and stop rules

Stop and reject the diagnostic if source/build/model/case/log fingerprints change, a baseline fails to reproduce, an output is incomplete, or an independent audit fails.  Otherwise report the complete action-outcome table and whether H14-C1 is falsified.  Do not tune rewards, entropy, sampling, architecture, or inference based on this receipt alone.

Any later successor requires a separate preregistration with a specific trainable causal hypothesis, current-source quality receipt, a capped pilot, independent audit, budget registration, and a fresh independent acceptance set under unchanged O23 gates.
