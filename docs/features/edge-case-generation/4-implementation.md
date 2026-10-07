# 4 Implementation: edge case generation

Each part justified by a test or a clause of the contract.

| Where | What | Justified by |
| ----- | ---- | ------------ |
| `analysis/edge_cases.py` `_infer_type` | checks `bool` before `int` (a `bool` is an `int` in Python) | T1.5 |
| `generate_edge_cases` loop | `copy.deepcopy(sample_input)` per case, then change one field | T1.8, T1.9 |
| `if field_type not in (int, float, str, bool): continue` | stops nested values at missing/null | T1.6 |
| `SQLI_PAYLOADS`, `XSS_PAYLOADS` | module constants, indexed in the label | T1.3, T1.7, T1.11 |
| `app.py` `generate_edge_cases_endpoint` | validates `sample_input` is a non-empty dict | T1.14 |
| `app.py` `confirm_selection_endpoint` | regenerates cases, filters by label set, refuses unknown labels | T1.15–T1.17 |
