"""Every headline number quoted in the memo must match reports/results.json.

Guards the rule "never invent or estimate results": if the data or code changes and the memo is
not updated, this test fails.
"""

import json

import pytest

from pipeline.config import REPORTS_DIR

RESULTS = REPORTS_DIR / "results.json"
MEMO = REPORTS_DIR / "memo.md"

pytestmark = pytest.mark.skipif(not RESULTS.exists(), reason="results.json not generated")


def pct(x: float) -> str:
    return f"{x:.0%}"


def expected_snippets() -> list[str]:
    r = json.loads(RESULTS.read_text())
    g, p = r["growth"], r["pricing"]
    c = g["concentration"]
    traders = c["overall"]["traders"]
    by_cat = {row["category"]: row for row in g["listing_mix"]["by_category"]}
    t = g["creator_track_record"]
    tr = t["terms"]["log_track_record"]
    q = t["quintiles"]
    plan = {row["category"]: row for row in g["listing_plan"]["plan"]}
    brier_bins = {row["trader_bin"]: row["brier"] for row in p["slope_by_traders"]}
    return [
        f"{g['n_markets']:,} Manifold markets",
        f"bottom {pct(1 - traders['share_of_markets_for_80pct'])} of listings",
        f"only {pct(traders['bottom_64pct_share'])} of trader participation",
        f"top {pct(traders['share_of_markets_for_80pct'])} generate 80%",
        f"{c['overall']['volume']['share_of_markets_for_80pct']:.1%} of markets carry 80%",
        f"{c['zero_trader_markets']:,} listings ({c['zero_trader_share']:.1%})",
        f"{pct(by_cat['Personal / Manifold-meta']['share_listings'])} of listings but "
        f"{pct(by_cat['Personal / Manifold-meta']['share_traders'])} of participation",
        f"median of {by_cat['Uncategorized']['median_traders']:.0f} traders",
        f"+{pct(t['doubling_track_record_pct'])} traders",
        f"95% CI +{pct(2 ** tr['ci_low'] - 1)} to +{pct(2 ** tr['ci_high'] - 1)}",
        f"median of {q[-1]['median_traders']:.0f} traders vs. {q[0]['median_traders']:.0f}",
        f"{q[-1]['median_traders'] / q[0]['median_traders']:.1f}x gap",
        f"{pct(g['drivers']['main']['plain_effects']['10x_creator_experience_pct'])} traders",
        f"**{pct(t['experience_10x_pct_with_track_record'])}**",
        f"Brier score {brier_bins['50+']:.3f} vs. {brier_bins['10-19']:.3f}",
        f"Brier {p['scores']['brier_price_24h']:.3f} vs. {p['scores']['brier_naive']:.3f}",
        f"calibration slope {p['logit_simple']['terms']['logit_p24']['coef']:.2f}",
        f"returns {pct(p['longshot_returns_24h']['under_10pct']['avg_return'])} on average",
        f"shift {g['listing_plan']['listings_moved_per_100']:.0f} of every 100 listings",
        f"+{plan['Technology']['change']} Technology",
        f"+{plan['Politics & law']['change']} Politics & law",
        f"+{plan['World']['change']} World",
        f"{plan['Sports']['change']} Sports",
        f"{plan['Culture']['change']} Culture",
        f"Sports gets {plan['Sports']['plan_first_100']} of 100",
        f"it gets {plan['Sports']['plan_by_volume_share']}",
        f"Technology ({plan['Technology']['plan_first_100']})",
    ]


@pytest.mark.parametrize("snippet", expected_snippets())
def test_memo_number_matches_results(snippet):
    memo = MEMO.read_text().replace("−", "-")  # memo uses typographic minus signs
    assert snippet.replace("−", "-") in memo, f"memo is missing or contradicts: {snippet!r}"


README = REPORTS_DIR.parent / "README.md"


def readme_snippets() -> list[str]:
    r = json.loads(RESULTS.read_text())
    g, p = r["growth"], r["pricing"]
    sl = p["logit_simple"]["terms"]["logit_p24"]
    c = g["concentration"]
    traders = c["overall"]["traders"]
    brier_bins = {row["trader_bin"]: row["brier"] for row in p["slope_by_traders"]}
    return [
        f"{g['n_markets']:,} Manifold markets",
        f"bottom {pct(1 - traders['share_of_markets_for_80pct'])} of listings generate only "
        f"{pct(traders['bottom_64pct_share'])} of trader participation",
        f"{c['zero_trader_markets']:,} listings ({c['zero_trader_share']:.1%})",
        f"Brier {brier_bins['50+']:.3f} vs. {brier_bins['10-19']:.3f}",
        f"Brier {p['scores']['brier_price_24h']:.3f} vs. {p['scores']['brier_naive']:.3f}",
        f"slope {sl['coef']:.2f}, 95% CI {sl['ci_low']:.2f}–{sl['ci_high']:.2f}",
        f"slope {p['out_of_sample']['test_slope']['coef']:.2f} on the latest 30%",
        f"{pct(g['creator_track_record']['experience_10x_pct_with_track_record'])} traders",
        f"+{pct(g['creator_track_record']['doubling_track_record_pct'])} traders",
        f"shifts {g['listing_plan']['listings_moved_per_100']:.0f} of every 100",
    ]


@pytest.mark.parametrize("snippet", readme_snippets())
def test_readme_number_matches_results(snippet):
    readme = README.read_text().replace("−", "-")
    assert snippet.replace("−", "-") in readme, f"README is missing or contradicts: {snippet!r}"
