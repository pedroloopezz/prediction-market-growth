"""Hand-checkable cases for the concentration metrics used in the growth analysis."""

import pandas as pd
import pytest

from pipeline.analysis.demand import gini, share_of_markets_for, top_share


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
