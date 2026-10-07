# 5 Refinement: edge case generation

## Turn 1 (retrofit): ran the tests, read what they said

**84-case suite, T1.\*: 17 of 17 passed on first run.** No code change.

| Sign | Points to | Action |
| ---- | --------- | ------ |
| Every test passed at once | the tests, or solid code | Checked against the retrofit caveat: the tests were written from the contract, not copied from the output; T1.5 (bool vs int) and T1.9 (no no-op case) are the ones that could have failed |
| `confirm-selection` regenerates all cases from the sample | the contract | Recorded as promised behaviour: the server holds no state, the client resends the sample |

## Next turn (concept first)

- Is a very long string of 5000 characters the right "very long"? The concept gives no number: make it a rule
- A float `NaN`/`Infinity` case is not imagined by the concept: a missing rule
