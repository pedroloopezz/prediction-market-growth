-- One row per tradable market resolved in the analysis window. Zero-trader markets are kept
-- on purpose: they are listings that attracted no demand.
WITH topic_hits AS (
    -- every (market, mapped category) pair; a market's category is its highest-priority hit
    SELECT d.market_key, c.category, c.priority
    FROM stg_market_details AS d, unnest(d.group_slugs) AS t(slug)
    JOIN seed_topic_categories AS c ON c.slug = t.slug
),
category AS (
    SELECT
        market_key,
        arg_min(category, priority)                AS category,
        bool_or(category = 'Politics & law')       AS has_politics,
        count(DISTINCT category)                   AS n_categories
    FROM topic_hits
    GROUP BY market_key
),
category_robust AS (
    -- robustness ordering: swap ONLY the Economics / Politics & law pair. A market moves only
    -- if its main category is Economics and it also carries a Politics & law topic; every other
    -- pairwise priority is unchanged.
    SELECT
        *,
        CASE WHEN category = 'Economics' AND has_politics THEN 'Politics & law'
             ELSE category END                     AS category_alt
    FROM category
),
prices AS (
    SELECT
        market_key,
        max(prob) FILTER (WHERE horizon_hours = 24) AS price_24h,
        max(prob) FILTER (WHERE horizon_hours = 1)  AS price_1h
    FROM stg_prices
    GROUP BY market_key
)
SELECT
    m.market_key,
    m.creator_id,
    m.creator_prior_markets,
    coalesce(c.category, 'Uncategorized')                     AS category,
    coalesce(c.category_alt, 'Uncategorized')                 AS category_alt,
    coalesce(c.n_categories, 0)                               AS n_categories,
    CASE
        WHEN m.outcome_type = 'BINARY' THEN 'binary'
        WHEN m.outcome_type = 'PSEUDO_NUMERIC' THEN 'numeric'
        ELSE 'multi-outcome'
    END                                                       AS market_type,
    m.outcome_type,
    m.open_time,
    m.close_time,
    m.resolution_time,
    -- millisecond precision: whole-second truncation turned sub-second markets into 0 hours
    (epoch_ms(m.close_time) - epoch_ms(m.open_time)) / 3600000.0 AS duration_hours,
    dayname(m.close_time)                                     AS close_day_of_week,
    m.unique_traders,
    m.volume,
    m.resolution,
    CASE m.resolution WHEN 'YES' THEN 1 WHEN 'NO' THEN 0 END  AS result,
    p.price_24h,
    p.price_1h,
    -- tradable contracts in the question: one for a single binary/numeric market
    CASE WHEN m.outcome_type IN ('BINARY', 'PSEUDO_NUMERIC') THEN 1
         ELSE d.n_answers END                                 AS n_answers,
    d.market_key IS NOT NULL                                  AS has_details
FROM stg_markets AS m
LEFT JOIN stg_market_details AS d USING (market_key)
LEFT JOIN category_robust AS c USING (market_key)
LEFT JOIN prices AS p USING (market_key)
WHERE m.is_resolved
  AND m.resolution_time >= TIMESTAMPTZ '{window_start}'
  AND m.resolution_time <  TIMESTAMPTZ '{window_end}'
  -- 5 markets in the Oct 5 snapshot have a creator-set close date before creation (data-entry
  -- errors); their duration is undefined, so they are excluded.
  AND m.close_time > m.open_time
