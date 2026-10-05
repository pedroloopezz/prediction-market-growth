"""Parser tests on real API responses saved in samples/ (no network)."""

import json

import duckdb
import pytest
from pydantic import ValidationError

from pipeline.config import SAMPLES_DIR
from pipeline.ingest.models import PRICE_DTYPES, Bet, full_row, lite_row, price_row
from pipeline.ingest.run import FULL_DTYPES, LITE_DTYPES, _write


def load(name: str):
    return json.loads((SAMPLES_DIR / name).read_text())


def test_lite_market_parses_with_types():
    for raw in load("manifold_markets_lite.json"):
        row = lite_row(raw)
        assert row["id"] == raw["id"]
        assert isinstance(row["created_time"], int)  # epoch milliseconds
        assert isinstance(row["unique_bettor_count"], int)
        assert isinstance(row["volume"], float)
        assert json.loads(row["raw_json"]) == raw  # raw record preserved untouched


def test_full_binary_market_has_topics_and_no_answers():
    row = full_row(load("manifold_market_full_binary.json"))
    assert row["outcome_type"] == "BINARY"
    assert row["resolution"] in {"YES", "NO"}
    assert row["group_slugs"] and all(isinstance(s, str) for s in row["group_slugs"])
    assert row["n_answers"] == 0


def test_full_multi_market_counts_answers():
    raw = load("manifold_market_full_multi.json")
    row = full_row(raw)
    assert row["outcome_type"] == "MULTIPLE_CHOICE"
    assert row["n_answers"] == len(raw["answers"]) > 1
    assert "answers" not in row  # summarised as a count, full list stays in raw_json


def test_full_market_drops_rich_text_description():
    raw = {**load("manifold_market_full_binary.json"), "description": {"type": "doc"}}
    row = full_row(raw)
    assert "description" not in json.loads(row["raw_json"])


def test_bet_probabilities_are_valid():
    for raw in load("manifold_bets.json"):
        bet = Bet.model_validate(raw)
        assert 0 <= bet.prob_before <= 1 and 0 <= bet.prob_after <= 1
        assert bet.created_time > 0


def test_missing_required_field_fails_loudly():
    raw = load("manifold_markets_lite.json")[0]
    raw.pop("uniqueBettorCount")
    with pytest.raises(ValidationError):
        lite_row(raw)


def test_all_null_page_still_unions_with_other_pages(tmp_path):
    """Regression: a page where `token` is all null used to be written as Parquet type NULL."""
    raw = load("manifold_markets_lite.json")[0]
    with_token = lite_row({**raw, "token": "MANA"})
    without_token = lite_row({k: v for k, v in raw.items() if k != "token"})
    _write([with_token], tmp_path / "a.parquet", "r1", "t", LITE_DTYPES)
    _write([without_token], tmp_path / "b.parquet", "r1", "t", LITE_DTYPES)
    n = duckdb.sql(f"SELECT count(*) FROM read_parquet('{tmp_path}/*.parquet')").fetchone()[0]
    assert n == 2


def test_full_rows_write_with_list_column(tmp_path):
    row = full_row(load("manifold_market_full_multi.json"))
    _write([row], tmp_path / "f.parquet", "r1", "t", FULL_DTYPES)
    slugs, n_answers = duckdb.sql(
        f"SELECT group_slugs, n_answers FROM read_parquet('{tmp_path}/f.parquet')"
    ).fetchone()
    assert slugs == row["group_slugs"] and n_answers == row["n_answers"]


def test_price_row_uses_prob_after_of_last_bet():
    bet = load("manifold_bets.json")[0]
    row = price_row(bet["contractId"], 24, bet["createdTime"] + 1, bet)
    assert row["prob"] == bet["probAfter"]
    assert row["bet_time"] < row["horizon_time"]


def test_price_row_without_any_bet_is_null_not_guessed():
    row = price_row("m1", 24, 1_700_000_000_000, None)
    assert row["prob"] is None and row["bet_id"] is None


def test_price_row_rejects_bet_from_another_market():
    bet = load("manifold_bets.json")[0]
    with pytest.raises(ValueError, match="belongs to"):
        price_row("some-other-market", 24, bet["createdTime"] + 1, bet)


def test_price_rows_write(tmp_path):
    bet = load("manifold_bets.json")[0]
    rows = [
        price_row(bet["contractId"], 24, bet["createdTime"] + 1, bet),
        price_row("m1", 1, 1_700_000_000_000, None),
    ]
    _write(rows, tmp_path / "p.parquet", "r1", "t", PRICE_DTYPES)
    n = duckdb.sql(f"SELECT count(prob) FROM read_parquet('{tmp_path}/p.parquet')").fetchone()[0]
    assert n == 1
