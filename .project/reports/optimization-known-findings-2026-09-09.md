# Optimization findings awaiting their owning task

These findings are not fixed or accepted by the current allocation task.

- task-22.1.2.1 / task-25.1.1.2: Humanoid::NeedTouch currently passes the boolean comparison (anim->GetOutgoingVelocity() != e_Velocity_Idle) into FloatToEnumVelocity. Review the intended velocity classification with boundary scenarios before changing touch decisions.
- task-22.1.2.1: AnimCollection::CrudeSelection rotational-side filtering adds queryIncomingToFenceSide (an enum) to fenceToOutgoingAngle; nearby calculations provide queryIncomingToFenceAngle. Confirm the intended angular test with turning fixtures; preserve a before/after behavior record.

Both are actual source findings, also reported by compiler enum/float warnings. They are intentionally tracked for behavior validation because fixing them during the identity-preserving allocation comparison would change its reference trajectory.

- Future acceptance design for task-22/task-25: the current task-21 allocation gate compares all trajectory checkpoints against the immutable pre-optimization binary. Intentional feel/AI behavior fixes can legitimately change those hashes while the manifest stales predecessor evidence on broad source scopes. Before those behavior changes, design an explicit versioned reference/acceptance strategy that still proves query/allocation equivalence for the same behavior revision. Do not silently overwrite the archived baseline, remove identity checks, or claim the old evidence applies to changed behavior. This is a known future gate-design dependency, not a current test failure.
