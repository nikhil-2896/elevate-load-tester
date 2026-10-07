# 2 Contract: target analysis

## Functions

- `analysis.sanity_check.sanity_check(url: str) -> dict`
  - malformed: `{"valid_format": False, "reachable": False, "error": "Malformed URL"}`
  - else: `{"valid_format": True, "reachable": bool, "status_code": int|None, "final_url": str|None, "headers": dict, "checked_with_method": "HEAD"|"GET"|"POST", "error"?: str}`
  - tries HEAD, then GET, then POST; stops at the first status other than 404/405
- `analysis.type_detector.detect_type(url: str, headers: dict) -> dict`
  - `{"classification": "api"|"website"|"unknown", "confidence": float (0..1), "signals": [...]}`
- `analysis.type_detector.try_find_sitemap(base_url) -> dict`
  - `{"found": bool, "sitemap_url": str, "raw"?: str, "error"?: "unreachable"}`
- `analysis.type_detector.extract_paths_from_sitemap(xml: str, max_paths=20) -> list[str]`
  - paths like `/about`; assets removed; capped at `max_paths`; `[]` on malformed XML; an index is followed one level

## Routes

### `POST /api/sanity-check`
| In | Out |
| -- | --- |
| `{"url": "..."}` well-formed | `200` sanity result |
| `url` empty or missing | `400 {"error": "url is required"}` |
| `url` malformed | `400` sanity result with `valid_format: false` |

### `POST /api/analyze`
| In | Out |
| -- | --- |
| `url` empty or missing | `400 {"error": "url is required"}` |
| malformed or unreachable | `400 {"sanity": {...}}` |
| reachable | `200 {"sanity", "type_detection"}` plus `"sitemap"` **only if** classified `website` |
