# 5 Refinement: load test dispatch

## Turn 1 (retrofit): ran the tests, read what they said

First run: **2 failed** (T3.3 at 999 and 1000 users), plus one failing test that was the *test's* fault (T3.9 reused a group id).

| You see | Refine | What was done |
| ------- | ------ | ------------- |
| T3.3 at 999, 1000 users: children of **100**, not ≤ 50 | the code, against the concept | `MAX_CHILD_JOBS` 10 → **20** in `load_test_runner.py`. `MAX_USERS` (1000) ÷ 50 = 20 children, so the "a worker is validated to 50 users" rule now holds for every accepted request. The contract and concept were right; the code contradicted its own comment |
| T3.9 `IntegrityError` on a repeated group id | the test | fixture now makes a unique id per group |
| Everything else (T3.1–T3.21 except above) passed | none | — |

**Result: 84 test cases across T0–T3, all passing.**

## Found, not yet changed (concept says nothing, so: next turn, concept first)

1. A worker deletes the SQS message in `finally`, even when the job fails: a failed job is not retried, and a job that raises before `_run_locust` is left `queued` forever
2. Two workers on one SQLite file would contend: the concept lists it as *not done*; one worker is the supported setup
3. Merged percentiles are weighted averages, not exact (stated in the concept)
4. CI builds and deploys the **API** image only; `Dockerfile.worker` and `k8s/worker-deployment.yaml` are not in the pipeline
