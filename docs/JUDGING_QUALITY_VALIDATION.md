# Judging Quality Validation for v1.0

JudgeAI should not be promoted from v0.9 to v1.0 based only on unit tests. The core product claim is about debate analysis, so the final gate needs real-round evaluation.

For each evaluation transcript, record:

1. Human reference decision, when available
2. Whether JudgeAI invented an argument, source, statistic, concession, or answer
3. Whether it correctly tracked major dropped arguments
4. Whether it respected speech timing and avoided rewarding new final-rebuttal offense
5. Whether it identified framework and weighing correctly
6. Whether CX concessions were quoted/interpreted in context
7. Whether each paradigm behaved differently for a defensible paradigm-specific reason
8. Whether the cross-paradigm diff accurately reflected the saved ballots
9. Whether recommendations were actionable and grounded in the round
10. Run-to-run stability for 1, 3, and 5-run settings

A prompt change should be re-evaluated against the same fixed corpus before it replaces a previously measured prompt. Improvements on one round are not enough to justify a global prompt change.

## Suggested v1.0 gate

- no invented evidence or arguments in the release evaluation set
- no silent failed runs
- no known crash on clean Windows install
- successful packaged-app smoke test on at least two machines
- external testers can configure a key, judge a round, reopen it, export it, and retry a paradigm without developer help
