# 1 Concept: edge case generation

> [!NOTE]
> This concept is subject to refinement during the
> development process. Until the contract exists, and
> wherever it is silent, this page is the source of
> truth.

## The goal

A tester gives **one sample request body** and gets back a set of labelled requests that probe how the target API handles bad input, and may pick which of them to run.

## The people

- **tester**: pastes a sample body, reads the cases, picks some
- **target API**: receives the chosen payloads during a load test (never contacted by this feature)
- **the load-test runner**: takes the confirmed cases and replays them

## The things

- **sample input**: a JSON object, the body of a request that works
- **edge case**: `label` (unique), `category`, `description`, `payload`
- **selection**: a list of labels the tester keeps

## The rules

1. Every field of the sample gets a case with that field **missing**, and one with it **null**
2. Only a **scalar** field (string, int, float, bool) gets more: a **wrong type**
3. A number gets **boundary** values (very large, negative, zero); a string gets **empty** and **very long**; a bool gets none
4. Only a **string** gets **known attacks** (3 SQL injection, 2 XSS)
5. A nested object or array gets only missing and null
6. Each case changes **exactly one field** of the sample; the sample itself is never altered
7. Labels are unique, so a label names one case
8. The same sample always gives the same cases
9. A selection may only name labels that exist; an empty selection is refused

## What it will not do

Infer a schema from OpenAPI, test nested fields individually, authenticate, or judge the target's answers. It generates and filters; it does not send.

## The artefact

| Field type | missing | null | wrong type | boundary | attacks |
| ---------- | :-----: | :--: | :--------: | :------: | :-----: |
| string     | ✓ | ✓ | ✓ | empty, very long | SQLi ×3, XSS ×2 |
| int, float | ✓ | ✓ | ✓ | very large, negative, zero | — |
| bool       | ✓ | ✓ | ✓ | — | — |
| object, array | ✓ | ✓ | — | — | — |
