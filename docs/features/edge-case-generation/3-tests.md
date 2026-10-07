# 3 Tests: edge case generation

Source: `code/tests/test_t1_edge_cases.py`. Layer: the function, then the routes once.

| ID | Question | Expect |
| -- | -------- | ------ |
| T1.1 | Missing, every field? | a case per field with exactly that field removed |
| T1.2 | Null, every field? | a case per field with that field `None` |
| T1.3 | A string field? | missing, null, wrong type, empty, very long, 3 SQLi, 2 XSS: ten labels, no more |
| T1.4 | A number field? | missing, null, wrong type, very large, negative, zero; **no** attacks |
| T1.5 | A bool field? | missing, null, wrong type; not treated as a number |
| T1.6 | Nested object, array? | missing and null only |
| T1.7 | Twice, same label? | labels unique |
| T1.8 | What leaks? | the sample is never mutated |
| T1.9 | A case that changes nothing? | no payload equals the sample |
| T1.10 | Shape? | every case has exactly `label, category, description, payload` |
| T1.11 | Twice? | same input, same output |
| T1.12 | The absent? | empty sample gives `[]` |
| T1.13 | Route count? | `total_cases == len(cases)` |
| T1.14 | Route refusals? | missing, `{}`, list, string sample: `400` |
| T1.15 | Selection? | confirm returns exactly the selected cases |
| T1.16 | Unknown? | unknown label: `400`, naming it |
| T1.17 | Empty? | empty or absent selection / sample: `400` |
