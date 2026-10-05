"""Hand-checkable cases for the concentration metrics used in the growth analysis."""

import pandas as pd
import pytest

from pipeline.analysis.demand import (
    allocate,
    bottom_share,
    gini,
    median_ci,
    share_of_markets_for,
    top_share,
)


def test_share_of_markets_for_80pct():
    # 80 of 100 traders sit in one market out of five -> 20% of markets reach 80%
    assert share_of_markets_for(pd.Series([80, 5, 5, 5, 5])) == pytest.approx(0.2)
    # perfectly even: need 4 of 5 markets to reach 80%
    assert share_of_markets_for(pd.Series([1, 1, 1, 1, 1])) == pytest.approx(0.8)


def test_zero_trader_markets_count_as_listings():
    # dead inventory adds markets but no traders, so the share needed falls
    assert share_of_markets_for(pd.Series([80, 20, 0, 0, 0, 0, 0, 0, 0, 0])) == pytest.approx(0.1)


def test_gini_bounds():
    assert gini(pd.Series([5, 5, 5, 5])) == pytest.approx(0.0)
    assert gini(pd.Series([0, 0, 0, 10])) == pytest.approx(0.75)  # max for n=4 is (n-1)/n


def test_top_share():
    assert top_share(pd.Series(range(1, 11)), 0.1) == pytest.approx(10 / 55)


def test_allocate_is_proportional_and_sums_to_total():
    shares = pd.Series({"a": 0.5, "b": 0.3, "c": 0.2})
    plan = allocate(shares)
    assert plan.to_dict() == {"a": 50, "b": 30, "c": 20}


def test_allocate_enforces_floor_and_still_sums_to_total():
    shares = pd.Series({"big": 0.97, "tiny1": 0.01, "tiny2": 0.02})
    plan = allocate(shares, total=100, floor=3)
    assert plan["tiny1"] == 3 and plan["tiny2"] == 3 and plan.sum() == 100


def test_allocate_largest_remainder_rounding():
    shares = pd.Series({"a": 1, "b": 1, "c": 1})  # 33.33 each -> one gets the leftover slot
    plan = allocate(shares, floor=0)
    assert plan.sum() == 100 and sorted(plan) == [33, 33, 34]


def test_bottom_share_is_complement_of_top():
    s = pd.Series(range(1, 11))
    assert bottom_share(s, 0.5) == pytest.approx((1 + 2 + 3 + 4 + 5) / 55)


def test_median_ci_brackets_the_median():
    med, lo, hi = median_ci(pd.Series(range(101)))
    assert med == 50 and lo < 50 < hi
