# Architecture

`boss-zhipin-scraper` is a deterministic local pipeline, not a pair of autonomous agents.

1. A confirmed CLI request becomes an immutable Strategy identity.
2. `StrategyRunner` creates or resumes a Cycle and a Run with one persistent 500-request budget.
3. Cities run sequentially. Each Strategy city fetches one list page, writes its candidates into SQLite with platform-ID and normalized-URL deduplication, and drains that page before requesting another.
4. List and detail BOSS operations stay serial. A single AI worker thread consumes validated complete JDs while the collector can fetch the next detail.
5. AI output is strategy-scoped and must pass strict JSON validation. Low-confidence roles may enter `manual_review`.
6. Every controlled Run close freezes qualified and review rows before atomically publishing a Run-specific workbook.

The crawler remains deterministic because request budgets, access restrictions, job identity, and resume checkpoints are safety boundaries. The AI worker cannot navigate BOSS or decide network recovery.

## Stop and resume

- `code: 37`, HTTP 403/429, and explicit restriction pages stop later BOSS requests immediately.
- The Run remains `waiting_for_access` until the user confirms access has recovered.
- `--refresh` starts a new completed Cycle only; it cannot bypass unfinished work.
- SQLite leases and heartbeats prevent duplicate active workers and recover stale `processing` rows.

## Storage layers

- `tasks` and `jobs`: legacy/local task projections.
- `strategies` and `strategy_runs`: stable search identity, Cycle/Run lifecycle, budget, and export snapshot.
- `job_catalog`: global JD identity and crawl state.
- `strategy_jobs`: strategy-specific AI result and review state.
