# 3 Tests: target analysis

Source: `code/tests/test_t2_analysis.py`. The network is stood in; no test touches the internet.

| ID | Question | Expect |
| -- | -------- | ------ |
| T2.1 | Malformed? | `valid_format` and `reachable` both false |
| T2.2 | At the edge? | `ftp://…` and `http://` are not well-formed |
| T2.3 | POST-only endpoint? | HEAD 405, GET 405, POST 200: reachable, `checked_with_method == "POST"` |
| T2.4 | Server error? | 503 on all: not reachable |
| T2.5 | Down? | connection error on all: not reachable, `error` present |
| T2.6 | 404 everywhere? | still reachable, `status_code == 404` |
| T2.7 | JSON? | `api` |
| T2.8 | HTML? | `website` |
| T2.9 | No signal? | `unknown`, confidence `0.0` |
| T2.10 | Path hint alone? | `api` |
| T2.11 | At the edge? | confidence never above 1 |
| T2.12 | Assets? | urlset gives `["/", "/about"]`; `.png`, `.css` dropped |
| T2.13 | Many? | capped at 20; `max_paths=5` gives 5 |
| T2.14 | Malformed XML? | `[]` |
| T2.15 | Sitemap index? | sub-sitemaps fetched; real pages returned, no `.xml` paths |
| T2.16 | Index in an index? | not followed: `[]` |
| T2.17 | Route refusals? | empty and malformed: `400` |
| T2.18 | Empty analyze? | `400` |
| T2.19 | Unreachable analyze? | `400` with `sanity` in the body |
| T2.20 | What leaks? | `sitemap` present for website, **absent** for API |
