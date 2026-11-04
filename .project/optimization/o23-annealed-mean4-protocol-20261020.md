# O23: one fixed within-seed mean of annealed checkpoints

The schema5 campaign is rejected: 955/1000 goals and fifth-family 177/200
miss its frozen 970/1000 and 180/200 validation gates. Independent audit
passed. No confirmation has been opened for these models.

Retrospective old-validation-only diagnosis found final-window goal ranges
of 1.5, 1, 6.5, 0 and 2 percentage points across the five fixed seeds.
This motivates one bounded smoothing candidate, without additional training.

Before generating derived weights, fix versions 7424, 7680, 7936, 8192,
equal weight 1/4 within each seed. Retain all five seeds. No window search,
best-checkpoint selection, cross-seed combination or controller changes.
The earlier rejected constant-rate mean4 remains rejected; these are newly
trained schema5 weights with an independently recorded provenance.

Validation uses the original 200 cases per model: total goals >=970/1000,
each seed >=180/200, each family >=180/200, observed pass and pass+goal
each >=40/200 per seed, at least 10 more goals than annealed final8192,
and at least 20 more than original legacy. Do not weaken any gate.

Budget: zero optimizer updates, five 200-episode evaluations, at most 300
seconds each and 2400 seconds overall, RSS <=512 MiB, output <=256 MiB.
The independent auditor must reconstruct every mean using exact rational
arithmetic and recompute every gate from raw episode rows.

Only a full validation and audit pass permits a separately registered fresh
confirmation excluding all recorded training and previous assessment history.
Main confirmation gates remain 930/170/170/40/40 and paired-bootstrap
95% improvement lower bound strictly greater than zero. A failure ends this
candidate; no alternative averaging windows will be evaluated.

Derived FPOL policies are inference-only. Original FPPO training states remain
unchanged and keep their source/build/ABI/resource compatibility checks.
