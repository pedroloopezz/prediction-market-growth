# How do Manifold's play-money prices compare with real-money markets?

Our numbers come from `reports/results.json` (`pricing` section) and are reproduced by `python -m pipeline.analysis.calibration`. Each published number has its page reference so it can be checked in the source PDF. Units and horizons differ between studies (noted per row), so this compares **direction and rough size**, not a like-for-like test.

| Measure | Manifold (this project) | Real-money evidence | Where in the source |
|---|---|---|---|
| Calibration slope at ~1 day before close (logistic recalibration; > 1 = underconfident, prices compressed toward 50%) | **1.25** (95% CI 1.19–1.31), one price per market 24 h before close, 8,482 markets | 12–24 h bin, trade-weighted: Kalshi **1.053** Sports, **1.006** Crypto, **1.477** Politics; Polymarket **1.059**, **0.996**, **1.277** | Le (2026), Table 15, p. 22 |
| Calibration slope ~1 hour before close | **1.32** (95% CI 1.25–1.39), price 1 h before close | Kalshi: the mean cell-level slope (averaged across domain × trade-size cells) rises from **0.99** within one hour of resolution to **1.32** beyond one month | Le (2026), p. 2 |
| Politics | **1.28** (Politics & law, 24 h) | 12–24 h bin: Kalshi **1.477**, Polymarket **1.277**. Across horizons, trade-weighted mean over the seven reliable bins (3 h to 1 month+): Polymarket **1.31**, Kalshi **1.64** | Le (2026), p. 2; definition in the Table 15 note, p. 22 |
| Sports | **1.11** (95% CI 0.95–1.27; can't reject 1) | Kalshi Sports is well calibrated from 0 to 48 hours (slopes **0.90–1.10**) and underconfident beyond one month (**1.74**) | Le (2026), p. 6 |
| Long shots: average return of buying YES below 10% | **−67%**, *pre-fee*, play money, 3,855 markets | Kalshi, *post-fee* for Takers: average loss rates for contracts priced 10¢ and under exceed **60%** | Bürgi, Deng & Whelan (2026), Section 3.3 and Figure 5, p. 17; also summarized in the introduction, p. 3 |
| Favorites: average return of buying YES above 50% | **+2.0%**, *pre-fee*, play money | Kalshi, post-fee: small positive returns above 50¢, statistically significant above 70¢ | Bürgi, Deng & Whelan (2026), p. 17 |
| Bias vs. time to expiration | Present at both 24 h and 1 h | Favorite–long-shot bias grows with time to expiration; markets are reasonably well calibrated when expiration is near | Page & Clemen (2013), abstract, p. 491 |

## Reading it

- **The direction matches the real-money evidence.** Long shots are overpriced and favorites underpriced, Politics is the most underconfident domain, and Sports is the closest to calibrated. Our 24 h Politics slope (1.28) sits between Polymarket and Kalshi in the same horizon bin (1.28 and 1.48). Our Sports slope (1.11) is slightly above theirs (about 1.05) and statistically consistent with 1.
- **The long-shot comparison is directional only.** Bürgi et al.'s 60%+ loss is *after* Kalshi's fees, for contracts at or below 10¢. Our −67% is *before* fees, on play money, for prices below 10%. Both say long shots lose most of what's put into them, but the numbers aren't directly comparable. Our figure is a size-of-mispricing measure, not a trading strategy.
- **The clear difference is close to resolution.** Le reports Kalshi's average slope at about 0.99 within the last hour; Manifold is at 1.32 one hour before close, even though its accuracy still improves (Brier 0.052 at 1 h vs. 0.075 at 24 h). A plausible explanation, which we haven't tested: with play money, the reward for pushing a near-certain market from 97% to 99% is tiny, while real-money traders are paid to close that gap.
- **Methods and status differ.**
  - Le (2026) is a single-author arXiv preprint. It estimates slopes on trades and reports cell-level or trade-weighted averages. Its Polymarket results exclude the two shortest bins because of timestamp noise (p. 5).
  - Bürgi, Deng & Whelan (2026) is a working paper using Kalshi's closing and daily prices for contracts open at least 24 h.
  - Page & Clemen (2013) is peer-reviewed.
  - We use one price per market at a fixed horizon.

## Sources

- Bürgi, C., Deng, W., & Whelan, K. (2026, January). *Makers and Takers: The Economics of the Kalshi Prediction Market.* Working paper, University College Dublin; also CESifo Working Paper 12122 and CEPR DP 20631. https://www.karlwhelan.com/Papers/Kalshi.pdf (page numbers refer to this 44-page version).
- Le, N. A. (2026). *Decomposing Crowd Wisdom: Domain-Specific Calibration Dynamics in Prediction Markets.* arXiv:2602.19520v1. National Economics University, Vietnam. https://arxiv.org/abs/2602.19520 (page numbers refer to the 22-page v1 PDF).
- Page, L., & Clemen, R. T. (2013). Do Prediction Markets Produce Well-Calibrated Probability Forecasts? *The Economic Journal*, 123(568), 491–513. https://doi.org/10.1111/j.1468-0297.2012.02561.x
