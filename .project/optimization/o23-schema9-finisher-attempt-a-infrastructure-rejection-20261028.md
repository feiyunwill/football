# Schema9 runner attempt A rejection ¡ª 2026-10-28

The retained attempt-A output is a non-candidate infrastructure failure. Seed 42 completed 8,192 updates and start reconstruction, but the runner then requested schema8-only continuous1024.log from the schema9 pilot. Schema9 registers full64.log instead.

No frozen O23 evaluation case, confirmation case, O24 process, or O25 process was opened. The corrected runner compares the first 64 rows of the seed-42 1,024-update chunk with full64.log.

