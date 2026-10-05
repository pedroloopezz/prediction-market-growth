# How do Manifold's play-money prices compare with real-money markets?

Our numbers come from `reports/results.json` (`pricing` section) and are reproduced by `python -m pipeline.analysis.calibration`. Published numbers are quoted from the cited papers. Units differ between studies (noted per row), so read this as a comparison of **direction and rough size**, not a like-for-like test.

| Measure | Manifold (this project) | Real-money evidence | Source |
|---|---|---|---|
| Calibration slope, ~1 day before close (logistic recalibration; >1 = underconfident, i.e. prices compressed toward 50%) | **1.25** (95% CI 1.19–1.31), 8,482 markets, price 24h before close | Mean slope rises from **0.99** within one hour of resolution to **1.32** beyond one month (Kalshi, cell-level averages over trades) | Le (2026) |
| Calibration slope ~1 hour before close | **1.32** (95% CI 1.25–1.39) | **0.99** within one hour of resolution | Le (2026) |
| Politics | **1.28** (Politics & law) | Persistently underconfident: mean slope **1.31** on Polymarket, **1.64** on Kalshi | Le (2026) |
| Sports | **1.11** (95% CI 0.95–1.27; can't reject 1) | Well calibrated at short-to-medium horizons (slopes **0.90–1.10**) | Le (2026) |
| Long shots: average return of buying YES below 10% | **−67%** (pre-fee, play money; 3,855 markets) | Contracts under 10¢ "lose over 60 percent" of the money invested | Bürgi, Deng & Whelan (2026) |
| Favorites: average return of buying YES above 50% | **+2.0%** (pre-fee, play money) | "a small positive rate of return" for contracts above 50¢ | Bürgi, Deng & Whelan (2026) |
| Bias vs. time to expiration | Bias present at 24h and 1h | Favorite–long-shot bias grows with time to expiration; markets are reasonably well calibrated close to expiration | Page & Clemen (2013) |

## Reading it

- **The direction matches the real-money evidence:** long shots are overpriced and favorites underpriced (a favorite–long-shot bias), and Politics is underconfident. Even on a play-money platform the pattern and its rough size line up with Kalshi and Polymarket.
- **The one clear difference is close to resolution.** Real-money markets converge to calibration within the last hour (slope 0.99); Manifold does not (1.32), even though its accuracy still improves (Brier 0.052 at 1h vs 0.075 at 24h). One plausible reason, which we haven't tested: with play money, the reward for pushing a near-certain market from 97% to 99% is tiny, so nobody bothers, while real-money traders are paid to close that gap.
- **Units differ.** Le (2026) weights by trades and reports cell-level averages across domains and trade sizes; Bürgi et al. use Kalshi's closing and daily prices; we use one price per market at a fixed horizon. Le (2026) is a single-author arXiv preprint and Bürgi et al. (2026) is a working paper; Page & Clemen (2013) is peer-reviewed.

## Sources

- Bürgi, C., Deng, W., & Whelan, K. (2026). *Makers and Takers: The Economics of the Kalshi Prediction Market.* Working paper, University College Dublin (January 2026 version; also CESifo WP 12122 and CEPR DP 20631). https://www.karlwhelan.com/Papers/Kalshi.pdf
- Le, N. A. (2026). *Decomposing Crowd Wisdom: Domain-Specific Calibration Dynamics in Prediction Markets.* arXiv:2602.19520. https://arxiv.org/abs/2602.19520
- Page, L., & Clemen, R. T. (2013). Do Prediction Markets Produce Well-Calibrated Probability Forecasts? *The Economic Journal*, 123(568), 491–513. https://ideas.repec.org/a/ecj/econjl/v123y2013i568p491-513.html
