"""Pricing analysis: can market prices be trusted as probabilities?

    python -m pipeline.analysis.calibration

Sample: binary markets resolved YES/NO with a price 24h before close. Main spec: >= 10 unique
traders; robustness at >= 5 and >= 20. Writes figures to reports/figures/ and numbers to the
"pricing" section of reports/results.json. Manifold is play money: see the README caveats.
"""

from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from statsmodels.tools.sm_exceptions import SingularMatrixWarning

from pipeline.analysis.common import (
    BLUE,
    MUTED,
    NON_EXCHANGE_CATEGORIES,
    TEXT,
    TEXT_2,
    finish_figure,
    load_mart,
    new_figure,
    source_line,
    write_results,
)

log = logging.getLogger("calibration")

MAIN_MIN_TRADERS = 10
ROBUST_MIN_TRADERS = (5, 20)
TRAIN_SHARE = 0.70
N_BUCKETS = 10
TRADER_BINS = [9, 19, 49, np.inf]
TRADER_LABELS = ["10-19", "20-49", "50+"]


# ---- metrics -------------------------------------------------------------------------------
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% interval for a proportion (well-behaved near 0 and 1, unlike Wald)."""
    if n == 0:
        return np.nan, np.nan
    p = k / n
    centre = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return centre - half, centre + half


def brier(p: pd.Series, y: pd.Series) -> float:
    return float(np.mean((p - y) ** 2))


def log_loss(p: pd.Series, y: pd.Series, eps: float = 1e-6) -> float:
    p = p.clip(eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def logit(p: pd.Series) -> pd.Series:
    return np.log(p / (1 - p))


def calibration_table(d: pd.DataFrame, price: str = "price_24h") -> pd.DataFrame:
    """10 equal-width price buckets: n, mean price, actual YES rate, Wilson 95% CI."""
    edges = np.linspace(0, 1, N_BUCKETS + 1)
    b = pd.cut(d[price], edges, include_lowest=True)
    g = d.groupby(b, observed=True)
    t = pd.DataFrame(
        {
            "n": g.size(),
            "mean_price": g[price].mean(),
            "yes_rate": g.result.mean(),
            "yes": g.result.sum(),
        }
    )
    ci = [wilson(int(k), int(n)) for k, n in zip(t.yes, t.n, strict=True)]
    t["ci_low"], t["ci_high"] = zip(*ci, strict=True)
    t["gap"] = t.yes_rate - t.mean_price  # > 0: YES happens more often than the price implied
    t.index = [f"{iv.left:.1f}-{iv.right:.1f}" for iv in t.index]
    return t.drop(columns="yes")


def scores(d: pd.DataFrame, base_rate: float) -> dict:
    y = d.result
    return {
        "n": len(d),
        "yes_rate": y.mean(),
        "brier_price_24h": brier(d.price_24h, y),
        "brier_price_1h": brier(d.price_1h, y),
        "brier_naive": brier(pd.Series(base_rate, index=d.index), y),
        "log_loss_price_24h": log_loss(d.price_24h, y),
        "log_loss_price_1h": log_loss(d.price_1h, y),
        "log_loss_naive": log_loss(pd.Series(base_rate, index=d.index), y),
        "naive_base_rate": base_rate,
    }


def longshot_returns(d: pd.DataFrame, price: str = "price_24h") -> dict:
    """Average return of a hypothetical 1-unit YES buy at the market price, by price band.

    A size-of-mispricing measure comparable to Burgi, Deng & Whelan (2026) on Kalshi. Play money,
    no fees: not a trading strategy.
    """
    bands = {
        "under_10pct": d[price] < 0.10,
        "10_to_50pct": d[price].between(0.10, 0.50),
        "over_50pct": d[price] > 0.50,
    }
    out = {}
    for name, mask in bands.items():
        g = d[mask]
        out[name] = {
            "n": len(g),
            "mean_price": g[price].mean(),
            "yes_rate": g.result.mean(),
            "avg_return": float((g.result / g[price] - 1).mean()),
        }
    return out


# ---- regressions ---------------------------------------------------------------------------
def fit_logit(formula: str, d: pd.DataFrame):
    groups = pd.factorize(d.creator_id)[0]
    return smf.logit(formula, d).fit(disp=False, cov_type="cluster", cov_kwds={"groups": groups})


def term(fit, name: str) -> dict:
    ci = fit.conf_int()
    return {
        "coef": fit.params[name],
        "se": fit.bse[name],
        "p": fit.pvalues[name],
        "ci_low": ci.loc[name, 0],
        "ci_high": ci.loc[name, 1],
    }


def summarise(fit, label: str) -> dict:
    return {
        "label": label,
        "n": int(fit.nobs),
        "pseudo_r2": fit.prsquared,
        "n_clusters": int(len(np.unique(fit.cov_kwds["groups"]))),
        "terms": {name: term(fit, name) for name in fit.params.index},
    }


def slope_by_group(d: pd.DataFrame, col: str, min_n: int = 200) -> pd.DataFrame:
    rows = []
    for level, g in d.groupby(col, observed=True):
        if len(g) < min_n or g.result.nunique() < 2:
            continue
        f = fit_logit("result ~ logit_p24", g)
        rows.append(
            {
                col: level,
                "n": len(g),
                **{f"slope_{k}": v for k, v in term(f, "logit_p24").items()},
                "intercept": f.params["Intercept"],
                "brier": brier(g.price_24h, g.result),
            }
        )
    return pd.DataFrame(rows).set_index(col)


# ---- out of sample -------------------------------------------------------------------------
def out_of_sample(d: pd.DataFrame) -> dict:
    """Fit the calibration curve on the earliest 70% by close time, score on the latest 30%."""
    d = d.sort_values("close_time")
    cut = int(len(d) * TRAIN_SHARE)
    train, test = d.iloc[:cut], d.iloc[cut:]
    f_train = fit_logit("result ~ logit_p24", train)
    f_test = fit_logit("result ~ logit_p24", test)
    recal = f_train.predict(test)  # raw price passed through the train-period correction
    base = train.result.mean()
    return {
        "train_period": [str(train.close_time.min().date()), str(train.close_time.max().date())],
        "test_period": [str(test.close_time.min().date()), str(test.close_time.max().date())],
        "n_train": len(train),
        "n_test": len(test),
        "train_slope": term(f_train, "logit_p24"),
        "train_intercept": term(f_train, "Intercept"),
        "test_slope": term(f_test, "logit_p24"),
        "test_intercept": term(f_test, "Intercept"),
        "test_brier_raw_price": brier(test.price_24h, test.result),
        "test_brier_recalibrated": brier(recal, test.result),
        "test_brier_naive": brier(pd.Series(base, index=test.index), test.result),
        "test_log_loss_raw_price": log_loss(test.price_24h, test.result),
        "test_log_loss_recalibrated": log_loss(recal, test.result),
        "test_log_loss_naive": log_loss(pd.Series(base, index=test.index), test.result),
    }


# ---- figure --------------------------------------------------------------------------------
def fig_reliability(t: pd.DataFrame, slope: dict, n: int) -> str:
    fig, ax = new_figure(7.2, 6.0)
    ax.plot([0, 1], [0, 1], color=MUTED, linewidth=1, linestyle="--")
    ax.text(0.06, 0.30, "dashed line =\nperfect calibration", color=TEXT_2, fontsize=8)
    yerr = np.vstack([t.yes_rate - t.ci_low, t.ci_high - t.yes_rate])
    ax.errorbar(
        t.mean_price, t.yes_rate, yerr=yerr, fmt="none", ecolor=BLUE, elinewidth=1.5, capsize=3
    )
    ax.plot(t.mean_price, t.yes_rate, color=BLUE, linewidth=2)
    ax.scatter(
        t.mean_price,
        t.yes_rate,
        s=np.clip(t.n / 8, 20, 160),
        color=BLUE,
        zorder=3,
        edgecolor="white",
        linewidth=1.5,
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.grid(axis="y", color="#e4e3df", linewidth=0.8)
    ax.set_xlabel("Market price 24h before close (bucket mean)", color=TEXT_2)
    ax.set_ylabel("Share that resolved YES (95% Wilson CI)", color=TEXT_2)
    worst = t.loc[t.gap.abs().idxmax()]
    ax.annotate(
        f"priced {worst.mean_price:.0%} → {worst.yes_rate:.0%} resolved YES",
        (worst.mean_price, worst.yes_rate),
        xytext=(10, -18),
        textcoords="offset points",
        fontsize=8.5,
        color=TEXT,
    )
    if slope["ci_low"] <= 1 <= slope["ci_high"]:
        verdict = "well calibrated"
    else:
        verdict = "overconfident" if slope["coef"] < 1 else "underconfident"
    return finish_figure(
        fig,
        f"Prices 24h before close are {verdict}",
        f"Calibration slope {slope['coef']:.2f} "
        f"(95% CI {slope['ci_low']:.2f}-{slope['ci_high']:.2f}; 1.00 = perfect). "
        "10 price buckets; dot size = markets per bucket",
        source_line(n),
        "pricing_reliability",
    )


# ---- main ----------------------------------------------------------------------------------
def sample(df: pd.DataFrame, min_traders: int) -> pd.DataFrame:
    d = df[df.result.notna() & df.price_24h.notna() & (df.unique_traders >= min_traders)].copy()
    d["result"] = d.result.astype(int)
    d["logit_p24"] = logit(d.price_24h)
    d["log_volume"] = np.log1p(d.volume)
    d["log_duration"] = np.log(d.duration_hours)
    d["trader_bin"] = pd.cut(d.unique_traders, TRADER_BINS, labels=TRADER_LABELS)
    return d


def run() -> dict:
    df = load_mart()
    d = sample(df, MAIN_MIN_TRADERS)
    base = d.result.mean()

    table = calibration_table(d)
    table_1h = calibration_table(d, "price_1h")
    m_simple = fit_logit("result ~ logit_p24", d)
    d["logit_p1"] = logit(d.price_1h)
    m_1h = fit_logit("result ~ logit_p1", d)
    m_full = fit_logit(
        "result ~ logit_p24 + C(category, Treatment('Sports')) + log_volume + log_duration", d
    )
    # Drop markets already near-certain a day out (likely outcome known before close)
    interior = d[(d.price_24h >= 0.01) & (d.price_24h <= 0.99)]
    m_interior = fit_logit("result ~ logit_p24", interior)

    robustness = {}
    for k in ROBUST_MIN_TRADERS:
        r = sample(df, k)
        f = fit_logit("result ~ logit_p24", r)
        robustness[f"min_traders_{k}"] = {
            **scores(r, r.result.mean()),
            "slope": term(f, "logit_p24"),
            "intercept": term(f, "Intercept"),
            "calibration_table": calibration_table(r)
            .reset_index(names="bucket")
            .to_dict("records"),
        }

    exchange = d[~d.category.isin(NON_EXCHANGE_CATEGORIES)]
    results = {
        "sample": {
            "rule": "binary, resolved YES/NO, price_24h present, >= 10 unique traders",
            "n": len(d),
            "yes_rate": base,
            "near_certain_24h_share": float(((d.price_24h < 0.01) | (d.price_24h > 0.99)).mean()),
        },
        "scores": scores(d, base),
        "calibration_table_24h": table.reset_index(names="bucket").to_dict("records"),
        "calibration_table_1h": table_1h.reset_index(names="bucket").to_dict("records"),
        "logit_simple": summarise(m_simple, "result ~ logit(price_24h)"),
        "logit_1h": summarise(m_1h, "result ~ logit(price_1h)"),
        "longshot_returns_24h": longshot_returns(d),
        "logit_full": summarise(m_full, "+ category (Sports base), log volume, log duration"),
        "logit_interior_only": {
            **summarise(m_interior, "price_24h within [0.01, 0.99]"),
            "n_dropped": len(d) - len(interior),
        },
        "slope_by_category": slope_by_group(d, "category").reset_index().to_dict("records"),
        "slope_by_traders": slope_by_group(d, "trader_bin").reset_index().to_dict("records"),
        "exchange_categories_only": {
            **scores(exchange, exchange.result.mean()),
            "slope": term(fit_logit("result ~ logit_p24", exchange), "logit_p24"),
        },
        "out_of_sample": out_of_sample(d),
        "robustness": robustness,
        "figures": {"reliability": fig_reliability(table, term(m_simple, "logit_p24"), len(d))},
    }
    write_results("pricing", results)
    log.info("pricing: n=%d slope=%.3f", len(d), m_simple.params["logit_p24"])
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with warnings.catch_warnings():
        warnings.simplefilter("error", SingularMatrixWarning)
        run()


if __name__ == "__main__":
    main()
