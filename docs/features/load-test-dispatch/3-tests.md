# 3 Tests: load test dispatch

Source: `code/tests/test_t3_dispatch.py`. SQS and the clock are stood in.

| ID | Question | Expect |
| -- | -------- | ------ |
| T3.1 | At the edge? | exactly 50 users: one job, one message, status `queued` |
| T3.2 | Above it? | 51 users: a group; `child_count` equals messages sent |
| T3.3 | Add up, and the last one? | for 51, 99, 100, 101, 237, 500, 999, 1000: children sum to the request and **none exceeds 50** |
| T3.4 | Fair? | child sizes differ by at most 1 |
| T3.5 | Same? | every child has the same target, path, cases, rate, duration |
| T3.6 | Twice? | child job ids are distinct and all belong to the group |
| T3.7 | Website? | message carries `paths`, not `cases` |
| T3.8 | Together? | statuses `[completed, failed]` → failed; `[completed, timeout]` → timeout; `[failed, timeout]` → failed; `[completed, running]` → running; `[queued, queued]` and `[completed, queued]` → queued; all completed → completed |
| T3.9 | Twice, again? | a finished group's merged CSV is returned, and is identical on the second read |
| T3.10 | Absent? | unknown id: `None` |
| T3.11 | Absent, route? | `404` |
| T3.12 | Group id? | status route answers for a group id |
| T3.13 | Merge? | counts and throughput summed; min and max across children |
| T3.14 | Total? | `Aggregated` row counts everything |
| T3.15 | Nothing? | merging no CSVs gives only an `Aggregated` row of 0 |
| T3.16 | Who may not? | users 0 / 1001, spawn 0 / 21, duration 0 / 301, text for a number, bad URL, empty URL, empty or non-list cases: all `400`, **nothing queued** |
| T3.17 | At the edge? | 1000 / 20 / 300 exactly: `202` |
| T3.18 | Shape? | `202`, `status: started`, `is_group` false for small |
| T3.19 | Default path? | no sitemap: the URL's own path |
| T3.20 | Bare host? | no sitemap, no path: `["/"]` |
| T3.21 | Compare? | missing id `400`; unknown ids `404` |
