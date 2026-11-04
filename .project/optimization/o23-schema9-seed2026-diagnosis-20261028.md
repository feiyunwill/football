# O23 Schema9 seed-2026 diagnostic ¡ª 2026-10-28

This read-only diagnosis uses the failed Schema9 attempt-B frozen O23 validation output. It is design evidence only and must not be reused as acceptance, confirmation, O24, or O25 evidence.

The five-seed result is an independently audited candidate rejection: 948/1,000 goals versus the frozen 970/1,000 gate. Seed 2026 produced 167/200 goals, versus the 180/200 per-seed gate. Its validation log SHA-256 is $hash.

| Group | Seed 2026 goals / 40 | Other four seeds' mean goals / 40 | Seed 2026 completed passes / 40 | Other four seeds' mean completed passes / 40 |
| --- | ---: | ---: | ---: | ---: |
| 0 | 33 | 39.00 | 31 | 39.00 |
| 1 | 40 | 40.00 | 40 | 40.00 |
| 2 | 31 | 39.75 | 26 | 38.25 |
| 3 | 32 | 38.75 | 37 | 39.00 |
| 4 | 31 | 37.75 | 35 | 39.75 |

There are 32 failed seed-2026 episodes that scored in at least three of the other four policies. They span groups 0, 2, 3, and 4; group 2 has the largest completed-pass shortfall. This establishes a seed-robustness problem correlated with missed passes and goals, but does not establish a causal sampler, optimizer, or policy explanation.

Next action: preregister at most one cross-seed-stability candidate, run a short resource-bounded pilot with untouched diagnostic cases, and only then register a fresh independent five-seed study with new acceptance data.
