# 1 Concept: load test dispatch

> [!NOTE]
> This concept is subject to refinement during the
> development process. Until the contract exists, and
> wherever it is silent, this page is the source of
> truth.

## The goal

A tester starts a load test, and gets one answer back: the run's **status** and, when it finishes, its **numbers**, however many users were asked for and whichever way it ran (here, or through the queue).

## The people

- **tester**: starts a run, polls it, compares two runs
- **API**: validates, records, hands the work on
- **worker**: takes a job from the queue and runs Locust
- **the target**: receives the load

## The things

- **job**: one Locust run: `users`, `spawn_rate`, `duration_seconds`, a status, a stats CSV
- **group**: one request split into several child jobs
- **status**: `queued` → `running` → `completed` | `failed` | `timeout`

## The rules

1. Limits: `1 ≤ users ≤ 1000`, `1 ≤ spawn_rate ≤ 20`, `1 ≤ duration_seconds ≤ 300`; outside, refused before anything is recorded or sent
2. `url` is an absolute http(s) URL; an API test needs a non-empty list of confirmed cases
3. Up to **50 users** is one job
4. Above 50, the request becomes a **group**: children add up to exactly the users asked, **none above 50**, sizes within one of each other
5. Every child carries the same target, cases/paths, spawn rate and duration
6. A group's status is the **worst of its children**: failed, then timeout, then (all completed) completed, then (any running) running, else queued
7. A finished group reports **one merged CSV**: counts and throughput summed, min/max across children, other columns weighted by request count, plus an `Aggregated` row. It is computed once and kept
8. A website test with no sitemap tests the URL's own path, or `/` for a bare host
9. Queue mode is a switch, not a different answer: same routes, same statuses

## What it will not do

Run more than one worker safely on one SQLite file; retry a failed job; recombine percentiles exactly (merged percentiles are a weighted approximation).

## The artefact

```
start ─ validate ─ ≤50 users → job ──────────────┐
                 └ >50 users → group → children ─┤→ queue / thread → worker → Locust → CSV
status ← worst-of(children) ← merge(CSVs) ←──────┘
```
