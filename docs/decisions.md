# Decisions log

What we chose, what else we considered, and why. One section per milestone.

## Data source: Manifold Markets public API (Oct 5)

- **Chose Manifold over Kalshi and Polymarket after reading their terms, before ingesting anything at scale.** Kalshi's and Polymarket's API terms restrict this kind of analysis and publication; Manifold's terms allow personal, non-commercial projects, so the code and findings can be public.
- **No data in the repo.** Manifold's Terms forbid compiling databases except as their data and API pages permit (personal, non-commercial analysis), so raw and processed data live only in the gitignored `data/` folder. The repo holds code, a few scrubbed sample responses for parser tests, and aggregate results. Anyone can rebuild the data with one command.
- **Trade-offs we accept.** Manifold uses play money (mana). So:
  - **Unique traders** (`uniqueBettorCount`) is the main growth metric, because it measures real-user engagement and play money doesn't distort it. Volume is reported alongside.
  - The after-fee profit check is dropped, because there are no real fees or P&L. In its place we add a play-money limitation and a comparison with published calibration research on real-money markets.
- **Live API, not the bulk dump.** Manifold's free dump includes every bet, so price history would have been easy, but it was last updated July 2024. Only the API covers the last 12 months.

## M1: API verification and market ingest

- **Ingest strategy: snapshot every market, then fetch details only for the window.** `/v0/markets` returns 1,000 "lite" markets per call, so a full snapshot (192,800 markets back to Dec 2021) takes 193 requests and about a minute. Topics and answer counts are only on the per-market endpoint, so we call it only for markets resolved since Oct 1, 2025 (25,384 markets). Alternative: pull markets topic by topic with `groupId`. We rejected it because topics are user-created and overlapping, and we'd still need per-market calls for answer counts.
- **Raw layer: typed columns plus the untouched JSON, in Parquet partitioned by run date.** Each record is validated with pydantic at ingest, so a renamed or missing field fails loudly instead of quietly becoming null. The full original JSON is kept in `raw_json` for auditing. Column types come from the model, not from pandas guessing page by page: on the first run, an all-null column was written as Parquet type `NULL` and broke reads across files. A regression test now covers this.
- **Rate limiting and retries.** We leave at least 0.15 s between requests (at most 400 per minute; Manifold allows 500 per IP). Rate-limit (429), 5xx and network errors are retried with exponential backoff plus jitter, up to 6 attempts; other client errors fail immediately. The full-market fetch uses 4 threads sharing one lock-protected rate limiter, which hides network latency without exceeding the limit. Runs are idempotent:
  - the snapshot is skipped if today's partition already exists (`--force` overrides);
  - the full-market fetch skips market ids already on disk and writes every 500 markets, so an interrupted run resumes where it stopped.
- **Scope filters set at ingest.** Polls and bounties aren't tradable markets, so they never enter the warehouse. Everything else stays in raw, and analysis filters (binary YES/NO only for calibration, minimum traders, time window) live in SQL, where they're visible and easy to change.
