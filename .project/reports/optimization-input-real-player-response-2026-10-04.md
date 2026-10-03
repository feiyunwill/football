# Native input: real player response during a stoppage

The previous input contract compared one player's position only after 30 frames of opposing buffered directions. Under the current AI trajectory, seed 43 enters a dead-ball interval after nine active frames. Both matches then deselect the player and place him at the same restart position, so the final-position comparison failed despite a real response to the inputs.

The contract now observes the same owned player after every step and requires at least eight active and divergent frames for each seed. It retains the buffered-input replay, pause/resume barrier, exact authoritative hash reconciliation, and correction checks.

Release and ASan/UBSan runs both passed with 3,902 assertions, 39 active response frames, 39 divergent response frames, 82 confirmed frames, and 74 corrected frames. The full `task-22.1.1.1` gate subsequently passed, including 3,116,103 input-contract assertions and all upstream framework, architecture, performance, and memory checks.
