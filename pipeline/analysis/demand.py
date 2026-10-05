"""Growth analysis: how concentrated is engagement, what is over/under-listed, and what drives it.

    python -m pipeline.analysis.demand

Writes figures to reports/figures/ and numbers to the "growth" section of reports/results.json.
Main engagement metric: unique traders per market (uniqueBettorCount). Volume is reported next
to it. Summing unique traders across markets counts trader-market participations: one person
trading ten markets counts ten times.
"""

from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
import patsy
import statsmodels.api as sm
import statsmodels.formula.api as smf
from matplotlib.patches import Patch
from statsmodels.tools.sm_exceptions import SingularMatrixWarning

from pipeline.analysis.common import (
    BLUE,
    MUTED,
    NON_EXCHANGE_CATEGORIES,
    ORANGE,
    TEXT,
    TEXT_2,
    finish_figure,
    load_mart,
    new_figure,
    source_line,
    write_results,
)

log = logging.getLogger("demand")

BASE_CATEGORY = "Sports"  # reference level: the anchor category for a real-money exchange
EXPERIENCE_BINS = [-1, 0, 9, 49, 199, 999, np.inf]
EXPERIENCE_LABELS = ["First market", "1-9", "10-49", "50-199", "200-999", "1,000+"]


# ---- concentration -------------------------------------------------------------------------
def share_of_markets_for(values: pd.Series, target: float = 0.8) -> float:
    """Smallest share of markets (ranked from most to least engaged) reaching `target` of total."""
    v = np.sort(values.to_numpy(dtype=float))[::-1]
    cum = np.cumsum(v) / v.sum()
    return (np.searchsorted(cum, target) + 1) / len(v)


def gini(values: pd.Series) -> float:
    v = np.sort(values.to_numpy(dtype=float))
    n = len(v)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(v) / (n * v.sum()))


def top_share(values: pd.Series, top: float) -> float:
    v = np.sort(values.to_numpy(dtype=float))[::-1]
    return v[: max(1, int(round(top * len(v))))].sum() / v.sum()


def bottom_share(values: pd.Series, bottom: float) -> float:
    """Share of the total coming from the least-engaged `bottom` fraction of markets."""
    v = np.sort(values.to_numpy(dtype=float))
    return v[: int(round(bottom * len(v)))].sum() / v.sum()


def median_ci(values: pd.Series, z: float = 1.96) -> tuple[float, float, float]:
    """Median with a distribution-free 95% CI from binomial order statistics (deterministic)."""
    v = np.sort(values.to_numpy(dtype=float))
    n = len(v)
    lo = max(int(np.floor(n / 2 - z * np.sqrt(n) / 2)), 0)
    hi = min(int(np.ceil(n / 2 + z * np.sqrt(n) / 2)), n - 1)
    return float(np.median(v)), float(v[lo]), float(v[hi])


def concentration(df: pd.DataFrame) -> dict:
    def stats(d: pd.DataFrame) -> dict:
        out = {"markets": len(d)}
        for metric, col in [("traders", "unique_traders"), ("volume", "volume")]:
            out[metric] = {
                "share_of_markets_for_80pct": share_of_markets_for(d[col]),
                "top_10pct_share": top_share(d[col], 0.10),
                "top_1pct_share": top_share(d[col], 0.01),
                "bottom_50pct_share": bottom_share(d[col], 0.50),
                "bottom_64pct_share": bottom_share(d[col], 0.64),
                "gini": gini(d[col]),
            }
        return out

    return {
        "overall": stats(df),
        "by_category": {c: stats(g) for c, g in df.groupby("category")},
        "zero_trader_markets": int((df.unique_traders == 0).sum()),
        "zero_trader_share": float((df.unique_traders == 0).mean()),
    }


# ---- listing mix ---------------------------------------------------------------------------
def listing_mix(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = df.groupby(by)
    t = pd.DataFrame(
        {
            "listings": g.size(),
            "traders": g.unique_traders.sum(),
            "volume": g.volume.sum(),
            "median_traders": g.unique_traders.median(),
            "mean_traders": g.unique_traders.mean(),
            "zero_trader_share": g.unique_traders.apply(lambda s: (s == 0).mean()),
        }
    )
    t["share_listings"] = t.listings / t.listings.sum()
    t["share_traders"] = t.traders / t.traders.sum()
    t["share_volume"] = t.volume / t.volume.sum()
    # > 1: the group attracts a bigger share of traders than its share of listings
    t["engagement_index"] = t.share_traders / t.share_listings
    return t.sort_values("engagement_index", ascending=False)


def records(t: pd.DataFrame) -> list[dict]:
    return t.reset_index().to_dict(orient="records")


# ---- listing plan --------------------------------------------------------------------------
def allocate(shares: pd.Series, total: int = 100, floor: int = 3) -> pd.Series:
    """Shelf share = demand share: split `total` slots in proportion to `shares`, at least
    `floor` each, rounding by largest remainder so the slots sum exactly to `total`."""
    fixed = pd.Series(0, index=shares.index, dtype=int)
    free = shares.copy()
    while True:
        slots = total - fixed.sum()
        raw = free / free.sum() * slots
        alloc = np.floor(raw).astype(int)
        rest = slots - alloc.sum()
        alloc[(raw - alloc).sort_values(ascending=False).index[:rest]] += 1
        below = alloc[alloc < floor].index
        if below.empty:
            return (fixed + alloc.reindex(fixed.index, fill_value=0)).astype(int)
        fixed[below] = floor  # pin under-floor categories and re-split the rest
        free = free.drop(below)


def listing_plan(df: pd.DataFrame, category_col: str = "category") -> pd.DataFrame:
    real = df[~df[category_col].isin(NON_EXCHANGE_CATEGORIES)]
    mix = listing_mix(real, [category_col])
    plan = pd.DataFrame(
        {
            "current_per_100": mix.share_listings * 100,  # Manifold's mix, exchange categories only
            "trader_share": mix.share_traders,
            "median_traders": mix.median_traders,
        }
    )
    plan["plan_first_100"] = allocate(plan.trader_share)
    plan["change"] = plan.plan_first_100 - plan.current_per_100
    return plan.sort_values("plan_first_100", ascending=False)


# ---- drivers model -------------------------------------------------------------------------
def add_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["log_traders"] = np.log1p(d.unique_traders)
    d["log_volume"] = np.log1p(d.volume)
    d["log_duration"] = np.log(d.duration_hours)
    d["log_answers"] = np.log(d.n_answers.clip(lower=1))
    d["log_prior_markets"] = np.log1p(d.creator_prior_markets)
    d["uncertainty"] = (d.price_24h - 0.5).abs()  # 0 = coin flip, 0.5 = near-certain
    d["log_track_record"] = np.log1p(d.creator_track_record)
    return d


def rhs(category_col: str = "category", answers: bool = True) -> str:
    terms = [
        f"C({category_col}, Treatment('{BASE_CATEGORY}'))",
        "log_duration",
        "C(close_day_of_week, Treatment('Monday'))",
        "log_prior_markets",
    ]
    if answers:  # constant (= log 1) within binary markets, so dropped there
        terms.insert(3, "log_answers")
    return " + ".join(terms)


def fit_clustered(formula: str, d: pd.DataFrame):
    groups = pd.factorize(d.creator_id)[0]
    return smf.ols(formula, d).fit(cov_type="cluster", cov_kwds={"groups": groups})


def fit_within_creator(formula: str, d: pd.DataFrame):
    """Same model with creator fixed effects (demean y and X within creator).

    Identifies each effect from variation *within* a creator's own markets, e.g. whether the
    same creator's markets draw more traders as that creator gains experience.
    """
    y, X = patsy.dmatrices(formula, d, return_type="dataframe")
    X = X.drop(columns="Intercept")
    keys = d.loc[y.index, "creator_id"].to_numpy()
    y_w = y - y.groupby(keys).transform("mean")
    X_w = X - X.groupby(keys).transform("mean")
    X_w = X_w.loc[:, X_w.abs().sum() > 1e-9]  # drop columns with no within-creator variation
    groups = pd.factorize(keys)[0]
    return sm.OLS(y_w, X_w).fit(cov_type="cluster", cov_kwds={"groups": groups})


def summarise(fit, label: str) -> dict:
    ci = fit.conf_int()
    terms = {
        name: {
            "coef": fit.params[name],
            "se": fit.bse[name],
            "p": fit.pvalues[name],
            "ci_low": ci.loc[name, 0],
            "ci_high": ci.loc[name, 1],
        }
        for name in fit.params.index
    }
    return {
        "label": label,
        "n": int(fit.nobs),
        "r2": fit.rsquared,
        "n_clusters": int(len(np.unique(fit.cov_kwds["groups"]))),
        "terms": terms,
    }


def category_effects(fit, category_col: str = "category") -> pd.DataFrame:
    """% difference in (1 + traders) vs the base category, holding the other factors fixed."""
    prefix = f"C({category_col}, Treatment('{BASE_CATEGORY}'))[T."
    rows = []
    ci = fit.conf_int()
    for name in fit.params.index:
        if name.startswith(prefix):
            rows.append(
                {
                    "category": name[len(prefix) : -1],
                    "pct_vs_base": np.exp(fit.params[name]) - 1,
                    "ci_low": np.exp(ci.loc[name, 0]) - 1,
                    "ci_high": np.exp(ci.loc[name, 1]) - 1,
                    "p": fit.pvalues[name],
                }
            )
    return pd.DataFrame(rows).sort_values("pct_vs_base", ascending=False)


def plain_effects(fit) -> dict:
    """Continuous effects translated into plain terms (log-log -> ratios)."""
    p = fit.params
    out = {
        "doubling_duration_pct": 2 ** p["log_duration"] - 1,
        "10x_creator_experience_pct": 10 ** p["log_prior_markets"] - 1,
    }
    if "log_answers" in p:
        out["doubling_answers_pct"] = 2 ** p["log_answers"] - 1
    if "uncertainty" in p:
        # moving 0.1 further from a coin flip (e.g. 50% -> 60% or 40%)
        out["plus_0.1_from_coinflip_pct"] = np.exp(0.1 * p["uncertainty"]) - 1
    return out


def track_record_table(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df.creator_track_record.notna()].copy()
    d["track_record_quintile"] = pd.qcut(
        d.creator_track_record, 5, labels=["Q1 (lowest)", "Q2", "Q3", "Q4", "Q5 (highest)"]
    )
    g = d.groupby("track_record_quintile", observed=True)
    return pd.DataFrame(
        {
            "markets": g.size(),
            "track_record_range": g.creator_track_record.agg(
                lambda s: f"{s.min():.1f}-{s.max():.1f}"
            ),
            "median_traders": g.unique_traders.median(),
        }
    )


def creator_experience_table(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(
        experience=pd.cut(df.creator_prior_markets, EXPERIENCE_BINS, labels=EXPERIENCE_LABELS)
    )
    g = d.groupby("experience", observed=True)
    return pd.DataFrame(
        {
            "markets": g.size(),
            "creators": g.creator_id.nunique(),
            "median_traders": g.unique_traders.median(),
            "mean_traders": g.unique_traders.mean(),
            "zero_trader_share": g.unique_traders.apply(lambda s: (s == 0).mean()),
        }
    )


# ---- figures -------------------------------------------------------------------------------
def fig_concentration(df: pd.DataFrame, conc: dict) -> str:
    fig, ax = new_figure()
    x = np.arange(1, len(df) + 1) / len(df) * 100
    ax.plot([0, 100], [0, 100], color=MUTED, linewidth=1, linestyle="--")
    ax.axhline(80, color=MUTED, linewidth=0.8)
    for col, metric, color, label in [
        ("unique_traders", "traders", BLUE, "Unique traders"),
        ("volume", "volume", ORANGE, "Volume"),
    ]:
        v = np.sort(df[col].to_numpy(dtype=float))[::-1]
        ax.plot(x, np.cumsum(v) / v.sum() * 100, color=color, linewidth=2, label=label)
        share = conc["overall"][metric]["share_of_markets_for_80pct"] * 100
        ax.scatter([share], [80], s=40, color=color, zorder=3, edgecolor="white", linewidth=1.5)
        ax.annotate(
            f"{share:.0f}% of markets",
            (share, 80),
            xytext=(8, -16),
            textcoords="offset points",
            color=TEXT,
            fontsize=9,
            fontweight="bold",
        )
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 101)
    ax.set_xlabel("Markets, ranked from most to least traded (cumulative %)", color=TEXT_2)
    ax.set_ylabel("Cumulative % of total", color=TEXT_2)
    ax.grid(axis="y", color="#e4e3df", linewidth=0.8)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    share = conc["overall"]["traders"]["share_of_markets_for_80pct"] * 100
    return finish_figure(
        fig,
        f"{share:.0f}% of markets generate 80% of trader participation",
        "Cumulative share of unique traders (one count per trader per market) and of volume",
        source_line(len(df)),
        "growth_concentration",
    )


def fig_listing_mix(mix: pd.DataFrame, n: int) -> str:
    real = mix.drop(index=NON_EXCHANGE_CATEGORIES, errors="ignore")
    real = real.sort_values("engagement_index")
    other = mix.loc[[c for c in NON_EXCHANGE_CATEGORIES if c in mix.index]]
    order = list(other.index[::-1]) + list(real.index)
    t = mix.loc[order]
    fig, ax = new_figure(8.0, 5.4)
    y = np.arange(len(t))
    h = 0.36
    is_other = np.array([c in NON_EXCHANGE_CATEGORIES for c in t.index])
    listing_colors = [MUTED if o else BLUE for o in is_other]
    trader_colors = ["#d9d8d3" if o else ORANGE for o in is_other]
    ax.barh(
        y + h / 2 + 0.02, t.share_listings * 100, h, color=listing_colors, label="Share of listings"
    )
    ax.barh(
        y - h / 2 - 0.02,
        t.share_traders * 100,
        h,
        color=trader_colors,
        label="Share of unique traders",
    )
    for yi, (sl, st) in enumerate(zip(t.share_listings, t.share_traders, strict=True)):
        ax.text(
            sl * 100 + 0.3, yi + h / 2 + 0.02, f"{sl:.0%}", va="center", fontsize=8, color=TEXT_2
        )
        ax.text(
            st * 100 + 0.3, yi - h / 2 - 0.02, f"{st:.0%}", va="center", fontsize=8, color=TEXT_2
        )
    ax.set_yticks(y, [f"{c}" for c in t.index])
    for label, o in zip(ax.get_yticklabels(), is_other, strict=True):
        label.set_color(TEXT_2 if o else TEXT)
    ax.axhline(len(other) - 0.5, color=MUTED, linewidth=0.8, linestyle=":")
    ax.text(
        ax.get_xlim()[1],
        len(other) - 0.42,
        "Manifold-specific / unclassified (excluded from listing plan)",
        ha="right",
        va="bottom",
        fontsize=7.5,
        color=TEXT_2,
    )
    ax.set_xlabel("% of all markets in the window", color=TEXT_2)
    handles = [
        Patch(color=BLUE, label="Share of listings"),
        Patch(color=ORANGE, label="Share of unique traders"),
    ]
    ax.legend(handles=handles, frameon=False, loc="upper right", fontsize=9)
    gap = real.share_traders - real.share_listings
    top_name = gap.idxmax()
    top = real.loc[top_name]
    return finish_figure(
        fig,
        f"{top_name} is {top.share_listings:.0%} of listings but "
        f"{top.share_traders:.0%} of trader participation",
        "Share of listings vs share of unique traders by category, sorted by engagement index",
        source_line(n),
        "growth_listing_mix",
    )


def fig_creator_experience(table: pd.DataFrame, n: int) -> str:
    fig, ax = new_figure(8.0, 4.4)
    x = np.arange(len(table))
    ax.bar(x, table.median_traders, width=0.6, color=BLUE)
    for xi, (m, k) in enumerate(zip(table.median_traders, table.markets, strict=True)):
        ax.text(xi, m + 0.3, f"{m:.0f}", ha="center", fontsize=9, color=TEXT)
        ax.text(xi, -1.6, f"{k:,} mkts", ha="center", fontsize=7.5, color=TEXT_2)
    ax.set_xticks(x, table.index)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", color="#e4e3df", linewidth=0.8)
    ax.set_ylabel("Median unique traders per market", color=TEXT_2)
    ax.set_xlabel("Markets the creator had made before this one", color=TEXT_2, labelpad=14)
    lo, hi = table.median_traders.min(), table.median_traders.max()
    return finish_figure(
        fig,
        f"The median market draws {lo:.0f}-{hi:.0f} traders at every creator-experience level",
        "Median unique traders per market by creator experience (raw, before controls)",
        source_line(n),
        "growth_creator_experience",
    )


def fig_category_effects(effects: pd.DataFrame, n: int) -> str:
    base = pd.DataFrame(
        [
            {
                "category": f"{BASE_CATEGORY} (baseline)",
                "pct_vs_base": 0.0,
                "ci_low": 0.0,
                "ci_high": 0.0,
                "p": np.nan,
            }
        ]
    )
    e = pd.concat([effects, base]).sort_values("pct_vs_base")
    fig, ax = new_figure(8.0, 4.8)
    y = np.arange(len(e))
    is_other = np.array([c in NON_EXCHANGE_CATEGORIES for c in e.category])
    colors = [MUTED if o else BLUE for o in is_other]
    ax.hlines(y, e.ci_low * 100, e.ci_high * 100, color=colors, linewidth=2)
    ax.scatter(
        e.pct_vs_base * 100, y, s=45, color=colors, zorder=3, edgecolor="white", linewidth=1.5
    )
    ax.axvline(0, color=TEXT_2, linewidth=1)
    ax.set_yticks(y, e.category)
    for label, o in zip(ax.get_yticklabels(), is_other, strict=True):
        label.set_color(TEXT_2 if o else TEXT)
    ax.set_xlabel(
        f"% difference in traders vs {BASE_CATEGORY} (95% CI), other factors held fixed",
        color=TEXT_2,
    )
    top = e[~is_other].iloc[-1]
    return finish_figure(
        fig,
        f"All else equal, {top.category} markets draw {top.pct_vs_base:+.0%} traders vs "
        f"{BASE_CATEGORY}",
        "OLS on log(1 + traders) with controls; 95% CIs clustered by creator",
        source_line(n),
        "growth_category_effects",
    )


def fig_listing_plan(plan: pd.DataFrame, n: int) -> str:
    t = plan.sort_values("plan_first_100")
    fig, ax = new_figure(8.0, 4.8)
    y = np.arange(len(t))
    h = 0.36
    ax.barh(y + h / 2 + 0.02, t.current_per_100, h, color=MUTED)
    ax.barh(y - h / 2 - 0.02, t.plan_first_100, h, color=BLUE)
    for yi, (cur, new) in enumerate(zip(t.current_per_100, t.plan_first_100, strict=True)):
        ax.text(cur + 0.3, yi + h / 2 + 0.02, f"{cur:.0f}", va="center", fontsize=8, color=TEXT_2)
        ax.text(
            new + 0.3,
            yi - h / 2 - 0.02,
            f"{new}",
            va="center",
            fontsize=9,
            color=TEXT,
            fontweight="bold",
        )
    ax.set_yticks(y, t.index)
    for label in ax.get_yticklabels():
        label.set_color(TEXT)
    handles = [
        Patch(color=MUTED, label="Manifold today (per 100 listings)"),
        Patch(color=BLUE, label="Proposed first 100 listings"),
    ]
    ax.legend(handles=handles, frameon=False, loc="lower right", fontsize=9)
    ax.set_xlabel("Listings per 100", color=TEXT_2)
    moved = t.change.clip(lower=0).sum()
    gainers = t[t.change > 0].sort_values("change", ascending=False).index[:2]
    return finish_figure(
        fig,
        f"Move ~{moved:.0f} of every 100 listings toward {' and '.join(gainers)}",
        "Split by each category's share of unique traders (floor 3); Personal/meta excluded",
        source_line(n),
        "growth_listing_plan",
    )


# ---- main ----------------------------------------------------------------------------------
def run() -> dict:
    df = add_features(load_mart())
    n = len(df)
    conc = concentration(df)

    mix_cat = listing_mix(df, ["category"])
    mix_cat_alt = listing_mix(df, ["category_alt"])
    mix_type = listing_mix(df, ["market_type"])
    mix_cat_type = listing_mix(df, ["category", "market_type"])
    real = df[~df.category.isin(NON_EXCHANGE_CATEGORIES)]
    mix_real = listing_mix(real, ["category"])  # shares among the 7 exchange-relevant categories

    f_main = f"log_traders ~ {rhs()}"
    m_main = fit_clustered(f_main, df)
    m_volume = fit_clustered(f"log_volume ~ {rhs()}", df)
    m_alt = fit_clustered(f"log_traders ~ {rhs('category_alt')}", df)
    binary = df[(df.market_type == "binary") & df.price_24h.notna()]
    m_binary = fit_clustered(f"log_traders ~ {rhs(answers=False)} + uncertainty", binary)
    m_within = fit_within_creator(f_main, df)
    tracked = df[df.creator_track_record.notna()]
    m_track = fit_clustered(f"log_traders ~ {rhs()} + log_track_record", tracked)
    plan = listing_plan(df)
    plan_alt = listing_plan(df, "category_alt")
    median_by_cat = (
        pd.DataFrame(
            [(c, *median_ci(g.unique_traders), len(g)) for c, g in df.groupby("category")],
            columns=["category", "median_traders", "ci_low", "ci_high", "markets"],
        )
        .set_index("category")
        .sort_values("median_traders", ascending=False)
    )

    exp_table = creator_experience_table(df)
    personal = mix_cat.loc["Personal / Manifold-meta"]

    figures = {
        "concentration": fig_concentration(df, conc),
        "listing_mix": fig_listing_mix(mix_cat, n),
        "creator_experience": fig_creator_experience(exp_table, n),
        "category_effects": fig_category_effects(category_effects(m_main), n),
        "listing_plan": fig_listing_plan(plan, n),
    }

    results = {
        "n_markets": n,
        "metric_note": "unique_traders summed across markets = trader-market participations",
        "concentration": conc,
        "listing_mix": {
            "by_category": records(mix_cat),
            "by_category_alt_ordering": records(mix_cat_alt),
            "by_market_type": records(mix_type),
            "by_category_and_type": records(mix_cat_type),
            "exchange_categories_only": records(mix_real),
        },
        "personal_meta": {
            "share_listings": personal.share_listings,
            "share_traders": personal.share_traders,
            "median_traders": personal.median_traders,
        },
        "drivers": {
            "main": {
                **summarise(m_main, "log(1+traders), all markets"),
                "category_effects": records(category_effects(m_main).set_index("category")),
                "plain_effects": plain_effects(m_main),
            },
            "binary_with_uncertainty": {
                **summarise(m_binary, "log(1+traders), binary markets with price_24h"),
                "plain_effects": plain_effects(m_binary),
            },
            "robust_volume_outcome": {
                **summarise(m_volume, "log(1+volume), all markets"),
                "category_effects": records(category_effects(m_volume).set_index("category")),
            },
            "robust_category_alt": {
                **summarise(m_alt, "log(1+traders), Politics & law ranked above Economics"),
                "category_effects": records(
                    category_effects(m_alt, "category_alt").set_index("category")
                ),
            },
            "robust_within_creator": {
                "n": int(m_within.nobs),
                "r2_within": m_within.rsquared,
                "log_prior_markets": {
                    "coef": m_within.params["log_prior_markets"],
                    "se": m_within.bse["log_prior_markets"],
                    "p": m_within.pvalues["log_prior_markets"],
                    "10x_creator_experience_pct": 10 ** m_within.params["log_prior_markets"] - 1,
                },
            },
        },
        "creator_experience_bins": records(exp_table),
        "creator_track_record": {
            "definition": "avg unique traders on the creator's markets that closed before this "
            "market opened; defined only with >= 3 such markets",
            **summarise(m_track, "log(1+traders) + log(1+track record), markets with a record"),
            "doubling_track_record_pct": 2 ** m_track.params["log_track_record"] - 1,
            "experience_10x_pct_with_track_record": 10 ** m_track.params["log_prior_markets"] - 1,
            "quintiles": records(track_record_table(df)),
        },
        "median_traders_by_category": records(median_by_cat),
        "listing_plan": {
            "rule": "100 slots split by share of unique traders across the 7 exchange categories, "
            "floor 3, largest-remainder rounding; Personal/meta and Uncategorized excluded",
            "plan": records(plan),
            "robust_category_alt": records(plan_alt),
            "listings_moved_per_100": plan.change.clip(lower=0).sum(),
        },
        "figures": figures,
    }
    write_results("growth", results)
    log.info("growth: %d markets, figures: %s", n, list(figures.values()))
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with warnings.catch_warnings():
        # a rank-deficient design means a coefficient is not identified: fail, don't report it
        warnings.simplefilter("error", SingularMatrixWarning)
        run()


if __name__ == "__main__":
    main()
