"""Build the DuckDB warehouse from raw Parquet: raw views -> staging -> mart.

    python -m pipeline.warehouse.build

Each SQL file in sql/ is a plain SELECT; this script materialises it as a table of the same
name, in the order below, and logs row counts per table to the _build_log table.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from pipeline.config import RAW_DIR, WAREHOUSE_PATH, WINDOW_END, WINDOW_START
from pipeline.ingest.models import PRICE_DTYPES
from pipeline.ingest.run import FULL_DTYPES

log = logging.getLogger("warehouse")

SQL_DIR = Path(__file__).parent / "sql"
SEEDS_DIR = Path(__file__).parent / "seeds"
_SQL_TYPE = {"string": "VARCHAR", "Int64": "BIGINT", "Float64": "DOUBLE", "boolean": "BOOLEAN"}
MODELS = ["stg_markets", "stg_market_details", "stg_prices", "mart_market_outcomes"]


def _raw_views(con: duckdb.DuckDBPyConnection) -> None:
    # The lite dataset is a full snapshot per run date: only the latest one is current.
    con.execute(f"""
        CREATE OR REPLACE VIEW raw_markets_lite AS
        SELECT * FROM read_parquet('{RAW_DIR}/markets_lite/*/*.parquet', hive_partitioning = true)
        WHERE run_date = (
            SELECT max(run_date)
            FROM read_parquet('{RAW_DIR}/markets_lite/*/*.parquet', hive_partitioning = true)
        )
    """)
    # full and prices are incremental: every partition is part of the current state.
    for name, dataset, dtypes, extra in [
        ("raw_markets_full", "markets_full", FULL_DTYPES, ["NULL::VARCHAR[] AS group_slugs"]),
        ("raw_prices", "prices", PRICE_DTYPES, []),
    ]:
        if list((RAW_DIR / dataset).glob("*/*.parquet")):
            source = f"read_parquet('{RAW_DIR}/{dataset}/*/*.parquet', hive_partitioning = true)"
            con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM {source}")
        else:  # not ingested yet: an empty view with the right columns keeps the build running
            log.warning("no raw files for %s yet; using an empty view", dataset)
            cols = [f"NULL::{_SQL_TYPE[t]} AS {c}" for c, t in dtypes.items()]
            cols += [*extra, "NULL::VARCHAR AS run_id", "NULL::VARCHAR AS fetched_at"]
            con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT {', '.join(cols)} WHERE false")


def _seeds(con: duckdb.DuckDBPyConnection) -> None:
    for csv in sorted(SEEDS_DIR.glob("*.csv")):
        source = f"read_csv('{csv}', header = true)"
        con.execute(f"CREATE OR REPLACE TABLE seed_{csv.stem} AS SELECT * FROM {source}")


def build(path: Path = WAREHOUSE_PATH) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("SET TimeZone = 'UTC'")  # all timestamps, windows and weekdays are UTC
    _raw_views(con)
    _seeds(con)
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    con.execute("""
        CREATE TABLE IF NOT EXISTS _build_log (
            run_id VARCHAR, built_at TIMESTAMPTZ, model VARCHAR, row_count BIGINT
        )
    """)
    counts = {}
    for model in MODELS:
        sql = (SQL_DIR / f"{model}.sql").read_text()
        sql = sql.format(window_start=WINDOW_START, window_end=WINDOW_END)
        con.execute(f"CREATE OR REPLACE TABLE {model} AS {sql}")
        counts[model] = con.execute(f"SELECT count(*) FROM {model}").fetchone()[0]
        con.execute(
            "INSERT INTO _build_log VALUES (?, now(), ?, ?)", [run_id, model, counts[model]]
        )
        log.info("%-22s %8d rows", model, counts[model])
    con.close()
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build()


if __name__ == "__main__":
    main()
