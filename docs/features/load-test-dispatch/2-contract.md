# 2 Contract: load test dispatch

## Functions (`load_test_runner`)

- `start_load_test(target_url, target_path, cases, users=5, spawn_rate=1, duration_seconds=30) -> (id: str, is_group: bool)`
- `start_website_load_test(target_url, paths, users=5, spawn_rate=1, duration_seconds=30) -> (id, is_group)`
- `get_job_status(job_id) -> dict | None`
- `get_group_status(group_id) -> dict | None` (adds `child_jobs`, `status`, and `aggregated_stats_csv` once completed)
- constants: `SPLIT_THRESHOLD = 50`, `MAX_CHILD_JOBS = 20`
- `stats_aggregator.merge_stats_csvs(list[str]) -> str` (CSV text; last row `Aggregated`)

Queue message (one per job): `{job_id, job_type: "api"|"website", target_url, users, spawn_rate, duration_seconds}` plus `target_path` and `cases` (api) or `paths` (website).

## Routes

### `POST /api/start-load-test`
Body: `{url, confirmed_cases[], users?, spawn_rate?, duration_seconds?}` (defaults 5, 1, 30)

| Case | Out |
| ---- | --- |
| valid | `202 {"job_id", "status": "started", "is_group": bool}` (`job_id` is the group id when `is_group`) |
| `url` missing, not http(s), or no host | `400` |
| `confirmed_cases` missing, empty, not a list | `400` |
| any number not an integer, or outside the limits | `400` |

### `POST /api/start-website-load-test`
Body: `{url, sitemap_raw?, users?, spawn_rate?, duration_seconds?}`. Same refusals (no `confirmed_cases`).
`202` adds `"paths_used": [...]`.

### `GET /api/load-test-status/<id>`
`200` job or group status; `404 {"error": "job_id not found"}`. A group id is tried first.

### `GET /api/jobs`
`200 {"jobs": [...], "job_groups": [...]}`, newest first, children not listed among jobs.

### `POST /api/compare-jobs`
Body `{job_id_a, job_id_b}` → `200 {"job_a", "job_b"}`; missing id `400`; unknown id `404`.
