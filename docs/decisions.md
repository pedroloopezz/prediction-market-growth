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

## Scope decisions after reviewing the M1 counts (Oct 5)

- **Window: markets resolved Oct 1, 2025 – Sep 30, 2026 (25,041 tradable markets).** A 24-month window would give 54,987 markets and more statistical power. We kept 12 months because a new exchange cares about current user behavior, and 25k markets is already plenty for the growth models.
- **Calibration sample: at least 10 unique traders (~8.5k binary YES/NO markets), with robustness checks at ≥5 and ≥20.** With only a handful of traders, a "price" is one or two people's opinion, not a market consensus. Ten is the line where the price reflects several independent bets, and it still leaves a large sample. Showing 5 and 20 tells us whether the result depends on that cut.
  - **No sampling:** about two API calls per market fit in roughly an hour, so a stratified sample would add complexity (and a weighting question) for no gain.
- **Zero-trader markets stay in the growth analysis.** The 670 markets nobody traded are real listings that drew no demand, i.e. dead inventory, which is exactly what a new exchange wants to avoid. Dropping them would make concentration look milder than it is.
- **Supply side: creator experience goes into the engagement model, and standard errors are clustered by creator.** Manifold is a two-sided marketplace: creators supply markets and traders supply demand. Whether experienced creators' markets draw more traders is a question about recruiting and keeping strong creators. We measure experience as the number of markets the creator made before this one, counted from the full snapshot. Deleted markets aren't in the API, so the count is a lower bound. Clustering by creator also absorbs correlation between one creator's markets (the same audience, the same resolution habits).

## M2: Pre-close prices, warehouse and data-quality tests

- **Price at a horizon = `probAfter` of the last bet strictly before it, from `GET /v0/bets?contractId=…&beforeTime=…&limit=1`.** Horizons are 24 h and 1 h before `close_time`. Manifold defines `close_time` as the earlier of the creator's close date and the resolution time, so a horizon can never fall after resolution.
  - Resting limit orders count as "bets". That's fine: placing one doesn't move the price, so its `probAfter` is still the market price at that moment.
  - If nobody had traded before the horizon, the price is **NULL rather than imputed** from the creator's opening probability, which is one person's guess, not a market price.
  - Alternative considered: reconstructing full price paths from every bet, which would mean thousands of calls on popular markets. We only need two points per market.
  - Known limitation: if a creator leaves a market open after the outcome is already public, the 24 h price can already reflect the answer. This would make prices look *better* calibrated than they are, so we treat any finding of "well calibrated" with that caveat.
- **Prices for every binary market open at least 24 h (14,580 markets × 2 horizons), not only the calibration set.** The engagement model uses |price_24h − 0.5| as its uncertainty measure, so it needs prices for low-traffic markets too. The calibration filters (YES/NO, ≥10 traders) are applied in SQL. No sampling.
- **Warehouse: plain-SELECT SQL models materialized in order by `build.py`.** The models run `raw views → stg_markets / stg_market_details / stg_prices → mart_market_outcomes`. Category mapping lives in a seed CSV (`seeds/topic_categories.csv`), so a reviewer can audit it without reading SQL. All timestamps, window boundaries and weekdays are UTC. Each build logs row counts per model to `_build_log`.
  - Why DuckDB: it reads Parquet directly, needs no server, and anyone can rebuild in minutes.
  - At scale this becomes Postgres/Snowflake, dbt for the models, Airflow/Dagster for scheduling, and incremental loads keyed on `lastUpdatedTime` instead of a daily full snapshot.
- **A data-quality test caught a bug in the robustness ordering.** My first version gave Politics & law priority 2.5, which also lifted it above Science, Technology and Culture, moving 691 markets that shouldn't have moved. It's now a strict pairwise swap: a market changes category only if its main category is Economics and it also carries a Politics & law topic (536 markets). The test asserts that nothing else moves.
- **Data-quality tests found 5 markets whose creator-set close date is before their creation date.** Their duration is undefined, so the mart excludes them with a commented filter. We didn't loosen the test.
- **Categories: Manifold's own taxonomy, extended to user topics.** Only 38% of markets carry one of Manifold's seven `*-default` topics, so using those alone would leave about 60% Uncategorized. We kept the seven as the category set and mapped the ~300 most common user topics into them in a reviewable seed CSV. That brings named-category coverage to about 86%; the remainder is mostly markets with no topic at all.
  - Markets with several topics take the highest-priority match (Personal/meta > Sports > Economics > Science > Technology > Culture > Politics & law > World). 32.5% of markets match more than one category, so the mart also carries `category_alt` (Politics & law ranked above Economics), and every category result is re-run on it as a robustness check.
  - Judgment calls: esports/gaming → Sports, because real exchanges list them there; courts, crime and US local topics → "Politics & law". Topics under 1% of markets (`prop-bets` 0.98%, `death-markets`, `effective-altruism`) stay Uncategorized.
  - "Personal / Manifold-meta" (personal goals, coin flips, community markets) is specific to Manifold. It's reported separately and excluded from the listing recommendation.

