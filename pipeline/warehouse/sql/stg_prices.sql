-- Market probability at each pre-close horizon: probAfter of the last bet strictly before
-- horizon_time = close_time - horizon_hours. prob is NULL when nobody had traded yet.
SELECT
    market_id                               AS market_key,
    horizon_hours,
    to_timestamp(horizon_time / 1000)       AS horizon_time,
    bet_id,
    to_timestamp(bet_time / 1000)           AS bet_time,
    prob
FROM raw_prices
QUALIFY row_number() OVER (PARTITION BY market_id, horizon_hours ORDER BY fetched_at DESC) = 1
