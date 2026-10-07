# Features, in turns

Each feature below follows [The Cycle](https://tiet-ucs503.github.io/bug-bounty/conduct/the-cycle/index.html):
**1 Concept → 2 Contract → 3 Tests → 4 Implementation → 5 Refinement**, and the refinement returns to the concept.

| Feature | Goal | Concept | Contract | Tests | Implementation | Refinement |
| ------- | ---- | ------- | -------- | ----- | -------------- | ---------- |
| Edge case generation | one sample body → labelled hostile requests | [1](edge-case-generation/1-concept.md) | [2](edge-case-generation/2-contract.md) | [3](edge-case-generation/3-tests.md) | [4](edge-case-generation/4-implementation.md) | [5](edge-case-generation/5-refinement.md) |
| Target analysis | a URL → reachable? API or website? which pages? | [1](target-analysis/1-concept.md) | [2](target-analysis/2-contract.md) | [3](target-analysis/3-tests.md) | [4](target-analysis/4-implementation.md) | [5](target-analysis/5-refinement.md) |
| Load test dispatch | start a run, split a big one, read the result | [1](load-test-dispatch/1-concept.md) | [2](load-test-dispatch/2-contract.md) | [3](load-test-dispatch/3-tests.md) | [4](load-test-dispatch/4-implementation.md) | [5](load-test-dispatch/5-refinement.md) |

Test IDs `T0.*`–`T3.*` appear in the test function names under `code/tests/`.
Run them: `cd code && python -m pytest -q`.

## Turn 1 is a retrofit

These three features were built before this cycle was written down. Turn 1
therefore wrote the concept and contract **from the running system**, then wrote the tests
against the contract, then let the tests judge the code. Each refinement page records what
the tests found. Later turns (the next feature, the next change) go concept-first.
