# O23 Schema15 first-step-entropy finisher preregistration — 2026-10-29

## Candidate and causal hypothesis

Candidate: `2v1_broad_firststep_entropy_finisher` (payload schema 15).

**H15:** Schema14's recurrent failures are driven in part by early action-distribution collapse.  Applying additional entropy regularization only to the first decision of each cooperative episode will increase early exploration without prescribing any action, allowing PPO's existing terminal/cooperation rewards to reinforce successful choices and improve independent 2v1 performance.

The causal premise is bounded by the independently audited Schema14 intervention: replacing only the first applied action changed the outcome on its universal failures, while full-episode global entropy changes at 0.015, 0.020, and 0.025 did not satisfy O23.  The intervention is therefore step-specific rather than action-specific: base entropy remains `0.020`; multiplier is `2.5` only at the first cooperative decision (`0.050` effective coefficient), and `1.0` thereafter.  It neither boosts, masks, labels, nor hard-codes any action.

## Frozen controls

- Keep Schema12's sampler, annealed schedule, rewards, architecture, inference, seeds, rollout/update budget, and O23 gates unchanged.
- The only training change is a transient per-sample entropy multiplier.  It is derivable from the persisted scenario variation and episode step; schema 15 is distinct from all earlier checkpoint payloads.
- No Schema14 case or action-intervention result may be used as acceptance data or as an action target.
- A fresh 200-case five-group acceptance set, with recorded hashes excluding Schema11–14 sets, is mandatory before any five-seed study.

## Gate sequence and stop rules

1. Current-source quality and checkpoint contract must pass.
2. One serial pilot capped at 30 minutes must reproduce checkpoint/resume and complete a held-out evaluation.  A separate auditor must pass before further work.
3. Register a five-seed serial budget before study execution.
4. Register fresh independent cases, then execute the five seeds serially and independently audit all receipts.
5. Acceptance remains unchanged: aggregate roadmap target at least 93%; frozen O23 acceptance total at least 970/1000; each seed at least 180/200; each group at least 180/200; and the existing cooperation and paired-statistical gates.

Stop and reject on any source/hash/decoder mismatch, pilot or audit failure, budget violation, non-fresh cases, or frozen-gate failure.  Do not open confirmation, O24, or O25 unless this candidate independently passes O23.
