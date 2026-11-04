# O23 schema9 finisher diagnostic protocol

## Motivation

Schema8 `midl_mean4` was rejected: 952/1000 goals and group five 176/200. Its completed-pass metrics passed. The diagnostic therefore targets post-pass finishing under group-five geometry, without changing any frozen evaluation or acceptance gate.

## Candidate

Introduce a new versioned schema9 scenario variation, distinct from schema8. It retains the deterministic legacy stream and every existing schema1--8 behavior. In its *training* sampler only, group five is selected more often from the non-legacy portion; the group-five geometry, policy interface, optimizer, action space and score reward remain unchanged. The candidate name and payload schema must be new. Existing checkpoints are incompatible by design.

## Pilot registration

- One seed: 42; fresh initialization; 64 updates split 32+32.
- Maximum wall time: 1,800 seconds; RSS cap 512 MiB; output cap 256 MiB.
- Build, training and evaluation are serial.
- Pilot may use no prospective or confirmation cases and has no candidate-selection authority.
- Required records: source/tool hashes, command argv, resource samples, split-resume equivalence, payload compatibility rejection against schema8, and group-five held-out *pilot* measurement from a newly registered pilot-only case set.

## Decision

Only if the pilot is operationally valid and improves the pilot-only group-five signal without reducing pass/joint metrics will a separately registered five-seed study be considered. The schema8 rejection, its gates, and its prospective confirmation cases remain immutable.
