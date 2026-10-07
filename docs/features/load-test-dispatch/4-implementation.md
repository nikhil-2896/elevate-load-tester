# 4 Implementation: load test dispatch

| Where | What | Justified by |
| ----- | ---- | ------------ |
| `app._validate_load_test_params` | integer parse, three range checks, run before anything is recorded | T3.16, T3.17 |
| `load_test_runner.SPLIT_THRESHOLD`, `_split_users` | child count `min(MAX_CHILD_JOBS, ceil(users/50))`, remainder spread one each | T3.1–T3.4 |
| `MAX_CHILD_JOBS = 20` | `MAX_USERS / SPLIT_THRESHOLD` | T3.3 (see refinement) |
| `_dispatch_single` | `USE_SQS` → `send_job_message`, else a daemon thread | T3.1, T3.5, T3.7 |
| `start_split_*` | group row, then one job row + one message per child | T3.2, T3.6 |
| `get_group_status` | worst-of precedence; merge once, then store | T3.8, T3.9 |
| `stats_aggregator.merge_stats_csvs` | sums, extremes, weighted averages, `Aggregated` row | T3.13–T3.15 |
| `app.start_website_load_test_endpoint` | sitemap paths, else `[parsed.path or "/"]` | T3.19, T3.20 |
| `worker.py` | long-poll SQS, run, delete the message | queue contract |
