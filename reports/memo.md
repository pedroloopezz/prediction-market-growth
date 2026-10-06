# List fewer, better markets

**To:** Leadership, new event-contract exchange · **Re:** What to list first, and why · **Data:** 25,036 Manifold markets resolved Oct 2025 – Sep 2026 (public API; play money). Every number below is reproduced by `python -m pipeline.run_all` and stored in `reports/results.json`.

**Bottom line.** Engagement on a prediction exchange is driven by *which* markets you list and *who* creates them, not by how many. A new exchange should launch with a curated shelf: fewer markets, from proven creators, concentrated where its own users' demand is.

---

### 1. Curate the long tail: most listings barely trade

- **The bottom 64% of listings generate only 20% of trader participation; the top 36% generate 80%.** Volume is even more concentrated: 10.5% of markets carry 80% of it. 667 listings (2.7%) drew no traders at all.
- Low-signal listings drive most of the tail. Manifold-specific personal and meta markets are 20% of listings but 13% of participation, and uncategorized markets (most have no topic tag at all) are 14% of listings with a median of 5 traders (vs. 10–17 in real categories).
- **Action:** set a listing bar (a clear category, resolution source and question), review listings that draw few traders in their first days, and track *traders per listing* rather than listing count. → `slide_1_long_tail.png`

### 2. Back proven creators: track record predicts demand, volume of listings doesn't

- **Each doubling of a creator's track record (average traders on their earlier, already-closed markets) goes with +44% traders** (95% CI +34% to +55%). Markets from top-quintile creators draw a median of 21 traders vs. 6 for the bottom quintile, a 3.5x gap.
- Experience alone doesn't help: 10x more prior markets is associated with −1% traders (not significant). With track record held fixed, it's **−15%**: prolific creators of equal quality draw fewer traders per market.
- **Action:** tier creators by track record; feature and fast-track the top tier; limit how many listings unproven creators can open at once. → `slide_2_creators.png`

### 3. Concentrate liquidity where demand is, and rebalance the mix

- **Thicker markets have more accurate prices.** Markets with 50+ traders reach a Brier score 0.053 vs. 0.086 for 10–19 traders (lower is better). Overall, prices a day before close are informative (Brier 0.075 vs. 0.225 for always guessing the base rate), but long shots are systematically overpriced (calibration slope 1.25; buying YES below 10% returns −67% on average, pre-fee and play money, as a size-of-mispricing measure, not a strategy). That's the same direction found on Kalshi and Polymarket.
- **First 100 listings, shelf share = engagement share (unique traders, floor 3).** What holds under both weightings: **more Technology (17 → 22 of 100) and less Culture (8 → 5; 3 by volume).** In full, shift 8 of every 100 listings from Manifold's current mix: **+5 Technology, +2 Politics & law, +1 World; −4 Sports, −3 Culture, −1 Science.** → `slide_3_listing_plan.png`
- Weighting by volume instead flips Sports (28 of 100 vs. 25 today). On a real-money exchange, that's the engagement vs. fee-revenue trade-off to test.

---

**Limitations.**
- **Play money:** incentives differ from a real-money exchange, and prices don't converge near close the way Kalshi's do.
- **Manifold's audience is tech- and AI-heavy:** Technology's lead likely reflects that. The transferable lesson is to *align listings with your own users' demand*, measured the same way on your first weeks of traffic.
- **All results are correlational.** Track record may capture a creator's audience rather than skill.
- **"Participation" counts a trader once per market,** not distinct people.
- **Categories:** we mapped ~300 user topics to categories (86% coverage); the results hold under an alternate category ordering.

**Next steps:** re-run the same pipeline on the client's own early traffic; A/B test creator tiers and a listing bar; add real-money data under a data license.
