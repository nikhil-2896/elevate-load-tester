# 2 Contract: edge case generation

What others may rely on. Nothing about how.

## Function

`analysis.edge_cases.generate_edge_cases(sample_input: dict) -> list[dict]`

Returns a list; each item has exactly the keys `label`, `category`, `description`, `payload`.
`category` is one of `missing_field`, `null_value`, `type_mismatch`, `boundary_value`, `known_attack`.
Labels: `missing_<f>`, `null_<f>`, `wrong_type_<f>`, `very_large_<f>`, `negative_<f>`, `zero_<f>`,
`empty_string_<f>`, `very_long_string_<f>`, `sqli_<f>_<0..2>`, `xss_<f>_<0..1>`.
An empty sample returns `[]`. The argument is not modified.

## Routes

### `POST /api/generate-edge-cases`

| In | Out |
| -- | --- |
| `{"sample_input": {…}}` | `200 {"total_cases": n, "cases": [...]}`, `n == len(cases)` |
| `sample_input` missing, empty, or not an object | `400 {"error": "sample_input (object) is required"}` |

### `POST /api/confirm-selection`

| In | Out |
| -- | --- |
| `{"sample_input": {…}, "selected_labels": [...]}` | `200 {"confirmed_count": n, "confirmed_cases": [...]}`, only the named cases |
| `sample_input` missing or not an object | `400` |
| `selected_labels` missing, empty, or not a list | `400` |
| a label that is not one of the generated labels | `400 {"error": "Unknown labels: [...]"}` |
