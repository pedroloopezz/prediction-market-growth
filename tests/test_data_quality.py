"""Data-quality tests on the built warehouse (run after `python -m pipeline.warehouse.build`).

Each test guards a specific way the analysis could silently go wrong.
"""

import duckdb
import pytest

from pipeline.config import WAREHOUSE_PATH, WINDOW_END, WINDOW_START

pytestmark = pytest.mark.skipif(
    not WAREHOUSE_PATH.exists(), reason="warehouse not built; run python -m pipeline.run_all"
)


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    c.execute("SET TimeZone = 'UTC'")
    yield c
    c.close()


def scalar(con, sql):
    return con.execute(sql).fetchone()[0]


def test_market_key_unique_and_not_null(con):
    # Duplicates would double-count listings in every share and Pareto calculation.
    assert scalar(con, "SELECT count(*) FROM mart_market_outcomes WHERE market_key IS NULL") == 0
    assert (
        scalar(con, "SELECT count(*) - count(DISTINCT market_key) FROM mart_market_outcomes") == 0
    )


def test_result_is_binary_and_only_for_yes_no(con):
    # Calibration needs a clean 0/1 outcome; CANCEL/MKT/multi-outcome must stay NULL.
    assert scalar(con, "SELECT count(*) FROM mart_market_outcomes WHERE result NOT IN (0, 1)") == 0
    assert (
        scalar(
            con,
            """
        SELECT count(*) FROM mart_market_outcomes
        WHERE (result IS NOT NULL) <> (market_type = 'binary' AND resolution IN ('YES', 'NO'))
    """,
        )
        == 0
    )


def test_prices_within_unit_interval(con):
    # A probability outside [0, 1] means a parsing or unit error.
    assert (
        scalar(
            con,
            """
        SELECT count(*) FROM mart_market_outcomes
        WHERE price_24h NOT BETWEEN 0 AND 1 OR price_1h NOT BETWEEN 0 AND 1
    """,
        )
        == 0
    )


def test_close_time_after_open_time(con):
    # Negative or zero durations would break log(duration) and signal bad timestamps.
    assert (
        scalar(con, "SELECT count(*) FROM mart_market_outcomes WHERE close_time <= open_time") == 0
    )
    # log(duration) in the drivers model needs a strictly positive duration (a whole-second
    # truncation once turned sub-second markets into 0 hours)
    assert scalar(con, "SELECT count(*) FROM mart_market_outcomes WHERE duration_hours <= 0") == 0


def test_every_price_row_joins_to_a_market(con):
    # Orphan prices would mean we fetched prices for the wrong ids.
    assert (
        scalar(
            con,
            """
        SELECT count(*) FROM stg_prices p
        LEFT JOIN mart_market_outcomes m USING (market_key)
        WHERE m.market_key IS NULL
    """,
        )
        == 0
    )


def test_look_ahead_guard(con):
    # The critical one: a price observed at or after close would leak the outcome and fake
    # perfect calibration. Every price must come from a bet strictly before its horizon, and
    # every horizon must sit strictly before close.
    assert (
        scalar(
            con,
            """
        SELECT count(*) FROM stg_prices p JOIN mart_market_outcomes m USING (market_key)
        WHERE p.prob IS NOT NULL
          AND NOT (p.bet_time < p.horizon_time AND p.horizon_time < m.close_time)
    """,
        )
        == 0
    )
    assert (
        scalar(
            con,
            """
        SELECT count(*) FROM stg_prices p JOIN mart_market_outcomes m USING (market_key)
        WHERE p.horizon_time <> m.close_time - to_hours(p.horizon_hours)
    """,
        )
        == 0
    )


def test_mart_is_inside_the_window(con):
    assert (
        scalar(
            con,
            f"""
        SELECT count(*) FROM mart_market_outcomes
        WHERE NOT (resolution_time >= TIMESTAMPTZ '{WINDOW_START}'
                   AND resolution_time < TIMESTAMPTZ '{WINDOW_END}')
    """,
        )
        == 0
    )


def test_every_market_has_details_and_a_category(con):
    # Missing full-market rows would silently push markets into 'Uncategorized'.
    assert scalar(con, "SELECT count(*) FROM mart_market_outcomes WHERE NOT has_details") == 0
    assert scalar(con, "SELECT count(*) FROM mart_market_outcomes WHERE category IS NULL") == 0


def test_every_eligible_binary_market_was_priced(con):
    # No sampling: each binary market open >= 24h must have both horizons fetched.
    assert (
        scalar(
            con,
            """
        SELECT count(*) FROM mart_market_outcomes m
        WHERE market_type = 'binary' AND duration_hours >= 24
          AND (SELECT count(*) FROM stg_prices p WHERE p.market_key = m.market_key) <> 2
    """,
        )
        == 0
    )


def test_row_counts_logged_for_latest_build(con):
    rows = con.execute("""
        SELECT model, row_count FROM _build_log
        WHERE run_id = (SELECT max(run_id) FROM _build_log)
    """).fetchall()
    logged = dict(rows)
    assert set(logged) == {
        "stg_markets",
        "stg_market_details",
        "stg_prices",
        "mart_market_outcomes",
    }
    assert all(n > 0 for n in logged.values())


CATEGORIES = {
    "Personal / Manifold-meta",
    "Sports",
    "Economics",
    "Science",
    "Technology",
    "Culture",
    "Politics & law",
    "World",
    "Uncategorized",
}


def test_categories_come_from_the_agreed_list(con):
    # A typo in the seed CSV would silently create a new category.
    found = {
        r[0] for r in con.execute("SELECT DISTINCT category FROM mart_market_outcomes").fetchall()
    }
    assert found <= CATEGORIES


def test_robustness_ordering_only_moves_economics_to_politics(con):
    # category_alt swaps one priority (Politics & law above Economics); nothing else may change.
    assert (
        scalar(
            con,
            """
        SELECT count(*) FROM mart_market_outcomes
        WHERE category <> category_alt
          AND NOT (category = 'Economics' AND category_alt = 'Politics & law')
    """,
        )
        == 0
    )


def test_creator_track_record_has_no_leakage(con):
    # Recompute by brute force for a sample: average traders over the creator's markets that
    # closed strictly before this market opened, and only when there are at least 3 of them.
    mismatches = scalar(
        con,
        """
        WITH sample AS (
            SELECT * FROM mart_market_outcomes USING SAMPLE 300 ROWS (reservoir, 42)
        ),
        brute AS (
            SELECT s.market_key, count(p.market_key) AS n, avg(p.unique_traders) AS avg_traders
            FROM sample s
            LEFT JOIN stg_markets p
              ON p.creator_id = s.creator_id AND p.close_time < s.open_time
            GROUP BY s.market_key
        )
        SELECT count(*) FROM sample s JOIN brute b USING (market_key)
        WHERE s.creator_closed_prior_markets <> b.n
           OR (b.n >= 3 AND abs(s.creator_track_record - b.avg_traders) > 1e-9)
           OR (b.n < 3 AND s.creator_track_record IS NOT NULL)
    """,
    )
    assert mismatches == 0
