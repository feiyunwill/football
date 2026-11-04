# O23 single-variable family reweighting

The preceding schema5 terminal policy (955/1000) and its fixed mean4
(965/1000) failed their preregistered 970/1000 gate. Neither is eligible
for new confirmation. Their complete evidence remains immutable.

Hypothesis: increasing exposure to the difficult fifth continuous family
improves generalization. Uniform exposure was present, so this is not a
missing-sampling fix or a claim of established causality.

## Task and unchanged contracts

Add task `2v1_broad_reweighted`, enum/payload schema6. Keep schemas0--5
semantics. Envelope FPPO version1, policy/reward/observation/network/PPO
parameters, geometry conditional on a family, and the schema5 learning-rate
schedule remain unchanged. Use legacy starts with probability20%, family4
with40%, and families0--3 with10% each. Episode-keyed RNG and partition
identity remain deterministic. Schema5 and6 must reject each other's FPPO.
Source/build/ABI/resource continuation guards remain strict.

## Pilot before any full campaign

Current-source full quality must pass. Run seed42,hidden64,epochs4,
minibatch64,rollout256,cadence10,episode_limit256:64 updates continuously
and independently32+32 across processes. Require identical FPPO, FPOL,
iteration records and native start reconstruction; verify every effective
learning rate and16 optimizer steps per update. Test schema5/6 and old
source rejection. Sampler contracts must check empirical frequencies,
geometry bounds, partition determinism and unchanged prior tasks.

Pilot cap:1800 seconds overall,512 MiB observed child RSS,256 MiB output.
No learning-performance evaluation or new confirmation data. Record actual
full64 time, memory and disk, then freeze a separate complete five-seed
budget before full training. Full training must not start before this audit.
Set per-seed wall cap to `ceil((full64_seconds*128*1.75+120)/60)*60`;
require this value <=5113 seconds. Total actual training child wall cap is
five times that value;full campaign observed child RSS <=512 MiB and output
<=2 GiB. If the measured projection cannot satisfy the ceiling,do not launch.

## Fixed full-campaign design, pending measured budget

Seeds42,123,2026,31415,271828;fresh initialization for each.8192 updates,
32 chunks of256; no intermediate performance evaluation or seed replacement.
Primary inference policy is fixed in advance:within-seed equal mean of
versions7424,7680,7936,8192,using binary64 fsum divided by4. This follows
the independently verified smoothing effect in the predecessor campaign.
No other window,checkpoint selection,cross-seed mixture or inference rule
will be tested. Raw final FPPO/FPOL is retained for real continuation and
provenance,not substituted for the preselected primary policy.

Only the original200 old-validation cases per model are evaluated initially.
Gates:total>=970/1000;each seed>=180/200;each family>=180/200;per-seed
observed pass and pass+goal each>=40/200;at least20 more goals than frozen
original legacy. Independent exact-rational parameter and raw-log audits
are mandatory. Comparison to other historical means is descriptive.

Only an eligible audited result permits a freshly preregistered confirmation
that excludes all recorded training,validation and prior confirmation history.
Main gates remain930/170/170/40/40 and10000 crossed paired-bootstrap
95% improvement lower bound strictly>0 against frozen O20 policies.
No weakening gates or retrying a rejected policy on fresh cases.

Builds,training and evaluation remain serial. A failed candidate is preserved
and returns to mechanism diagnosis. O24 stability/pressure/2v2 and O25
current-source installation/resume/1000-episode archive replay remain required
before the long-term objective can be marked complete.
