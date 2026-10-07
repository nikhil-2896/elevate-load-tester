# 4 Implementation: target analysis

| Where | What | Justified by |
| ----- | ---- | ------------ |
| `sanity_check.is_valid_url_format` | scheme in (http, https) and a netloc | T2.1, T2.2 |
| `check_reachability` | HEAD, GET, POST loop; `reachable = status < 500`; stop unless 404/405 | T2.3–T2.6 |
| `detect_type` | weighted signals: JSON 0.8, HTML 0.7, path hint 0.6; ties go to API | T2.7–T2.11 |
| `try_find_sitemap` | one GET of `/sitemap.xml`, 5 s timeout | T2.20 |
| `_looks_like_page` + `NON_PAGE_EXTENSIONS` | drops assets | T2.12 |
| `extract_paths_from_sitemap(_depth)` | index detected by root tag; recursion capped at depth 1; first 5 sub-sitemaps | T2.15, T2.16 |
| `app.analyze_endpoint` | sitemap only when `classification == "website"` | T2.20 |
