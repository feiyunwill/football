# O23 Schema12 group-4 action trace diagnosis — 2026-10-29

This independently audited mechanism diagnostic replayed all 40 already-evaluated group-4 cases for each final Schema12 policy. It exactly reproduced the group-4 goal counts: 36, 34, 36, 33, and 34 for seeds 42, 123, 2026, 31415, and 271828.

For seeds 42, 123, 2026, and 271828, all 40 first decisions were policy action 5, including every failed case. Seed 31415 instead used actions 4, 5, and 6 for 22, 7, and 11 cases, and had the lowest group-4 score. Failures occur under both patterns. The evidence establishes a group-wide weakness and seed-dependent first-decision divergence, but no action-specific causal repair. Future work must not hard-code actions or select on these cases.

Schema12's acceptance data are now design-only. A successor must be separately preregistered and use a fresh acceptance set with the unchanged O23 gates.
