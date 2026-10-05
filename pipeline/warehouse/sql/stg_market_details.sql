-- Topics and answer counts from the full-market fetch; latest fetch wins if fetched twice.
SELECT
    id                              AS market_key,
    group_slugs,
    n_answers,
    should_answers_sum_to_one
FROM raw_markets_full
QUALIFY row_number() OVER (PARTITION BY id ORDER BY fetched_at DESC) = 1
