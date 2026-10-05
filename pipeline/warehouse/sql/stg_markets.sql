-- One row per tradable market from the latest lite snapshot, with readable timestamps.
-- creator_prior_markets counts the creator's earlier tradable markets (any status, any date),
-- i.e. experience at the moment this market was created. Deleted markets are not in the API,
-- so this is a lower bound.
WITH tradable AS (
    SELECT *
    FROM raw_markets_lite
    WHERE outcome_type NOT IN ('POLL', 'BOUNTIED_QUESTION')
)
SELECT
    id                                               AS market_key,
    creator_id,
    question,
    outcome_type,
    mechanism,
    to_timestamp(created_time / 1000)                AS open_time,
    to_timestamp(close_time / 1000)                  AS close_time,
    to_timestamp(resolution_time / 1000)             AS resolution_time,
    is_resolved,
    resolution,
    unique_bettor_count                              AS unique_traders,
    volume,
    total_liquidity,
    row_number() OVER (
        PARTITION BY creator_id ORDER BY created_time, id
    ) - 1                                            AS creator_prior_markets
FROM tradable
