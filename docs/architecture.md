# Architecture

```mermaid
flowchart LR
    API["Manifold public API<br/>/markets · /market/{id} · /bets"]

    subgraph ingest["pipeline/ingest"]
        C["ManifoldClient<br/>rate limit ≤400/min · retries + backoff · cursor pagination"]
        M["pydantic models<br/>validate fields, explicit dtypes"]
    end

    subgraph raw["data/raw (Parquet, gitignored)"]
        L["markets_lite/<br/>full snapshot per run_date"]
        F["markets_full/<br/>topics + answers (incremental)"]
        P["prices/<br/>24h & 1h pre-close (incremental)"]
    end

    subgraph wh["pipeline/warehouse → data/warehouse.duckdb"]
        S1["stg_markets<br/>+ creator_prior_markets"]
        S2["stg_market_details"]
        S3["stg_prices"]
        SEED["seed_topic_categories.csv"]
        MART["mart_market_outcomes<br/>1 row per market · category, category_alt,<br/>track record, price_24h / price_1h"]
    end

    subgraph an["pipeline/analysis"]
        D["demand.py<br/>concentration · listing mix · drivers · listing plan"]
        K["calibration.py<br/>reliability · Brier · logit slope · out-of-sample"]
        SL["slides.py"]
    end

    OUT["reports/<br/>results.json · figures/ · memo.md"]
    T["tests/<br/>parsers · client · data quality (look-ahead guard)<br/>analysis math · memo numbers"]

    API --> C --> M --> L & F & P
    L --> S1
    F --> S2
    P --> S3
    S1 & S2 & S3 & SEED --> MART
    MART --> D & K
    D & K --> OUT
    OUT --> SL --> OUT
    MART -.checked by.-> T
    OUT -.checked by.-> T
```

**One command:** `python -m pipeline.run_all` runs ingest → warehouse build → analyses → slide charts → tests. `--skip-ingest` rebuilds everything from the raw Parquet on disk in about 10 seconds.

**Idempotency.** The lite snapshot is written once per run date (an atomic directory swap). Full markets and prices are incremental, keyed on market id and (market id, horizon), and flushed every 500 items, so an interrupted run resumes where it stopped. Every run writes a manifest with its `run_id` and row counts to `data/raw/_runs/`, and every warehouse build logs row counts to `_build_log`.

**What changes at scale.**

| Layer | Now | At scale |
|---|---|---|
| Storage | Local DuckDB | Postgres or Snowflake |
| SQL models | Plain SELECTs run in order by `build.py` | dbt, with the pytest checks as dbt tests |
| Orchestration | `run_all` | Airflow or Dagster |
| Loads | Daily full snapshot | Incremental, keyed on `lastUpdatedTime` |
| CI | Tests run locally | CI on every push |
