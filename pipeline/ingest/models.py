"""Pydantic models for the Manifold records we ingest.

Only the fields the analysis needs are declared (and required where the analysis can't work
without them). Everything else is ignored here but preserved in the raw_json column, so a
schema change upstream fails loudly instead of silently producing nulls.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class LiteMarket(_Base):
    id: str
    creator_id: str = Field(alias="creatorId")
    question: str
    outcome_type: str = Field(alias="outcomeType")
    mechanism: str
    created_time: int = Field(alias="createdTime")  # epoch ms
    # min(creator-chosen close date, resolution time)
    close_time: int | None = Field(default=None, alias="closeTime")
    is_resolved: bool = Field(alias="isResolved")
    resolution: str | None = None  # YES / NO / MKT / CANCEL, or an answer id for multi-outcome
    resolution_time: int | None = Field(default=None, alias="resolutionTime")
    resolution_probability: float | None = Field(default=None, alias="resolutionProbability")
    unique_bettor_count: int = Field(alias="uniqueBettorCount")
    volume: float
    total_liquidity: float | None = Field(default=None, alias="totalLiquidity")
    last_bet_time: int | None = Field(default=None, alias="lastBetTime")
    token: str | None = None  # MANA or CASH; absent on lite markets in practice


class Answer(_Base):
    id: str
    text: str
    volume: float | None = None
    is_other: bool | None = Field(default=None, alias="isOther")


class FullMarket(LiteMarket):
    group_slugs: list[str] = Field(default_factory=list, alias="groupSlugs")
    answers: list[Answer] = Field(default_factory=list)
    should_answers_sum_to_one: bool | None = Field(default=None, alias="shouldAnswersSumToOne")


class Bet(_Base):
    id: str
    contract_id: str = Field(alias="contractId")
    created_time: int = Field(alias="createdTime")
    prob_before: float = Field(alias="probBefore")
    prob_after: float = Field(alias="probAfter")
    answer_id: str | None = Field(default=None, alias="answerId")
    amount: float
    is_filled: bool | None = Field(default=None, alias="isFilled")


_PANDAS_DTYPE = {str: "string", int: "Int64", float: "Float64", bool: "boolean"}


def pandas_dtypes(model: type[BaseModel]) -> dict[str, str]:
    """Explicit nullable dtypes per column, derived from the model's annotations.

    Without this, a page where a column happens to be all null gets written with Parquet type
    NULL and no longer unions with the other pages.
    """
    out = {}
    for name, field in model.model_fields.items():
        base = next((t for t in _PANDAS_DTYPE if field.annotation in (t, t | None)), None)
        if base is not None:
            out[name] = _PANDAS_DTYPE[base]
    return out


def lite_row(raw: dict) -> dict:
    """Flatten one lite market into a typed row plus the untouched raw JSON."""
    m = LiteMarket.model_validate(raw)
    return {**m.model_dump(), "raw_json": json.dumps(raw)}


def full_row(raw: dict) -> dict:
    """Flatten one full market. Topics stay a list; answers are summarised as a count."""
    raw = {k: v for k, v in raw.items() if k != "description"}  # rich-text blob, not needed
    m = FullMarket.model_validate(raw)
    row = m.model_dump(exclude={"answers"})
    row["n_answers"] = len(m.answers)
    row["raw_json"] = json.dumps(raw)
    return row


PRICE_DTYPES = {
    "market_id": "string",
    "horizon_hours": "Int64",
    "horizon_time": "Int64",
    "bet_id": "string",
    "bet_time": "Int64",
    "prob": "Float64",
    "raw_json": "string",
}


def price_row(market_id: str, horizon_hours: int, horizon_time: int, raw_bet: dict | None) -> dict:
    """Market probability at a horizon = probAfter of the last bet strictly before it.

    No bet before the horizon means nobody had traded yet, so the price is left null rather than
    guessed from the creator's starting probability.
    """
    row = {
        "market_id": market_id,
        "horizon_hours": horizon_hours,
        "horizon_time": horizon_time,
        "bet_id": None,
        "bet_time": None,
        "prob": None,
        "raw_json": None,
    }
    if raw_bet is not None:
        bet = Bet.model_validate(raw_bet)
        if bet.contract_id != market_id:
            raise ValueError(f"bet {bet.id} belongs to {bet.contract_id}, not {market_id}")
        row.update(
            bet_id=bet.id,
            bet_time=bet.created_time,
            prob=bet.prob_after,
            raw_json=json.dumps(raw_bet),
        )
    return row
