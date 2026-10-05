"""Ingest Manifold data into raw Parquet.

    python -m pipeline.ingest.run markets   # snapshot of every lite market (~1 min)
    python -m pipeline.ingest.run full      # full markets in the window: topics, answers (~1 h)
    python -m pipeline.ingest.run prices    # pre-close prices for binary markets (~75 min)

Layout:  data/raw/<dataset>/run_date=YYYY-MM-DD/part-*.parquet
Every run writes a manifest with its run_id and row counts to data/raw/_runs/.

Idempotency:
  * markets: one snapshot per run date. Re-running the same day is a no-op unless --force.
  * full, prices: incremental. Keys already present on disk are skipped, and results are
    flushed every CHUNK items so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import uuid
from collections.abc import Callable, Hashable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from pipeline.config import PRICE_HORIZONS_HOURS, RAW_DIR, WINDOW_END, WINDOW_START
from pipeline.ingest.manifold_client import ManifoldClient
from pipeline.ingest.models import (
    PRICE_DTYPES,
    FullMarket,
    LiteMarket,
    full_row,
    lite_row,
    pandas_dtypes,
    price_row,
)

log = logging.getLogger("ingest")

# Polls and bounties are not tradable markets, so they never enter the warehouse.
NON_MARKET_TYPES = ("POLL", "BOUNTIED_QUESTION")
CHUNK = 500
WORKERS = 4
HOUR_MS = 3600 * 1000

LITE_DTYPES = {**pandas_dtypes(LiteMarket), "raw_json": "string"}
FULL_DTYPES = {**pandas_dtypes(FullMarket), "n_answers": "Int64", "raw_json": "string"}


def _ms(date: str) -> int:
    return int(datetime.fromisoformat(date).replace(tzinfo=UTC).timestamp() * 1000)


def _partition(dataset: str, run_date: str) -> Path:
    return RAW_DIR / dataset / f"run_date={run_date}"


def _write(
    rows: list[dict], path: Path, run_id: str, fetched_at: str, dtypes: dict[str, str]
) -> None:
    df = pd.DataFrame(rows).astype(dtypes)
    df["run_id"] = run_id
    df["fetched_at"] = fetched_at
    path.parent.mkdir(parents=True, exist_ok=True)
    # write-then-rename so readers never see a half-written file
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.rename(path)


def _manifest(run_id: str, dataset: str, counts: dict) -> None:
    out = RAW_DIR / "_runs" / f"{run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"run_id": run_id, "dataset": dataset, **counts}, indent=2))
    log.info("run %s %s: %s", run_id, dataset, counts)


def _latest_lite() -> str:
    latest = sorted((RAW_DIR / "markets_lite").glob("run_date=*"))[-1]
    return f"{latest}/*.parquet"


def _existing_keys(dataset: str, columns: str) -> set:
    files = [str(f) for f in (RAW_DIR / dataset).glob("run_date=*/*.parquet")]
    if not files:
        return set()
    rows = duckdb.connect().execute(f"SELECT DISTINCT {columns} FROM read_parquet(?)", [files])
    return {r if len(r) > 1 else r[0] for r in rows.fetchall()}


def _fetch_incremental(
    client: ManifoldClient,
    dataset: str,
    todo: list[Hashable],
    fetch_one: Callable[[Any], dict],
    dtypes: dict[str, str],
    run_id: str,
    run_date: str,
) -> dict:
    """Fetch `todo` with a small thread pool, flushing a Parquet file every CHUNK items.

    Threads only hide network latency: the client's lock still enforces the global rate limit.
    """
    part = _partition(dataset, run_date)
    fetched_at = datetime.now(UTC).isoformat()

    def safe(key):
        try:
            return fetch_one(key)
        except Exception as exc:  # deleted/private market etc.: log and move on
            log.warning("%s %s skipped: %s", dataset, key, exc)
            return None

    n_written = n_errors = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for chunk_no, start in enumerate(range(0, len(todo), CHUNK)):
            results = list(pool.map(safe, todo[start : start + CHUNK]))
            rows = [r for r in results if r is not None]
            n_errors += len(results) - len(rows)
            if rows:
                _write(
                    rows, part / f"part-{run_id}-{chunk_no:04d}.parquet", run_id, fetched_at, dtypes
                )
                n_written += len(rows)
            log.info("%s: %d / %d fetched", dataset, start + len(results), len(todo))
    return {
        "fetched_this_run": n_written,
        "skipped_errors": n_errors,
        "requests": client.n_requests,
    }


# ---- datasets --------------------------------------------------------------------------------
def ingest_markets(client: ManifoldClient, run_id: str, run_date: str, force: bool) -> None:
    part = _partition("markets_lite", run_date)
    if part.exists() and not force:
        log.info("markets_lite for %s already exists; skipping (use --force)", run_date)
        return
    tmp = part.with_name(part.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    fetched_at = datetime.now(UTC).isoformat()
    n = 0
    for i, page in enumerate(client.iter_market_pages()):
        rows = [lite_row(m) for m in page]
        _write(rows, tmp / f"part-{i:04d}.parquet", run_id, fetched_at, LITE_DTYPES)
        n += len(page)
        if i % 25 == 0:
            log.info("page %d: %d markets so far", i, n)
    # swap in atomically so a crash never leaves a half-written snapshot behind
    shutil.rmtree(part, ignore_errors=True)
    tmp.rename(part)
    _manifest(run_id, "markets_lite", {"rows": n, "requests": client.n_requests})


def ingest_full(client: ManifoldClient, run_id: str, run_date: str, since: str) -> None:
    """Full market (topics + answers) for every tradable market resolved on/after `since`."""
    candidates = [
        r[0]
        for r in duckdb.connect()
        .execute(
            f"""
        SELECT id FROM read_parquet('{_latest_lite()}')
        WHERE is_resolved AND resolution_time >= ? AND outcome_type NOT IN {NON_MARKET_TYPES}
        ORDER BY resolution_time DESC
        """,
            [_ms(since)],
        )
        .fetchall()
    ]
    done = _existing_keys("markets_full", "id")
    todo = [i for i in candidates if i not in done]
    log.info("full markets: %d candidates, %d to fetch", len(candidates), len(todo))
    counts = _fetch_incremental(
        client,
        "markets_full",
        todo,
        lambda i: full_row(client.get_market(i)),
        FULL_DTYPES,
        run_id,
        run_date,
    )
    _manifest(run_id, "markets_full", {"since": since, "candidates": len(candidates), **counts})


def ingest_prices(client: ManifoldClient, run_id: str, run_date: str) -> None:
    """Probability at 24h and 1h before close for binary markets resolved in the window.

    Eligible: binary, resolved in [WINDOW_START, WINDOW_END), open at least 24h. Every resolution
    and trader count is included, because the engagement model needs uncertainty for all binary
    markets; the calibration filters (YES/NO, >=10 traders) are applied later in SQL.
    """
    markets = (
        duckdb.connect()
        .execute(
            f"""
        SELECT id, close_time FROM read_parquet('{_latest_lite()}')
        WHERE is_resolved AND outcome_type = 'BINARY'
          AND resolution_time >= ? AND resolution_time < ?
          AND close_time - created_time >= 24 * {HOUR_MS}
        ORDER BY resolution_time DESC
        """,
            [_ms(WINDOW_START), _ms(WINDOW_END)],
        )
        .fetchall()
    )
    close = dict(markets)
    candidates = [(mid, h) for mid, _ in markets for h in PRICE_HORIZONS_HOURS]
    done = _existing_keys("prices", "market_id, horizon_hours")
    todo = [k for k in candidates if k not in done]
    log.info(
        "prices: %d markets x %d horizons, %d to fetch",
        len(markets),
        len(PRICE_HORIZONS_HOURS),
        len(todo),
    )

    def fetch_one(key: tuple[str, int]) -> dict:
        market_id, hours = key
        horizon = close[market_id] - hours * HOUR_MS
        return price_row(market_id, hours, horizon, client.get_last_bet_before(market_id, horizon))

    counts = _fetch_incremental(client, "prices", todo, fetch_one, PRICE_DTYPES, run_id, run_date)
    _manifest(run_id, "prices", {"markets": len(markets), "candidates": len(candidates), **counts})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="dataset", required=True)
    sub.add_parser("markets").add_argument("--force", action="store_true")
    sub.add_parser("full").add_argument(
        "--since", default=WINDOW_START, help="resolution date lower bound (UTC)"
    )
    sub.add_parser("prices")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    now = datetime.now(UTC)
    run_id = f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    run_date = f"{now:%Y-%m-%d}"
    with ManifoldClient() as client:
        if args.dataset == "markets":
            ingest_markets(client, run_id, run_date, args.force)
        elif args.dataset == "full":
            ingest_full(client, run_id, run_date, args.since)
        else:
            ingest_prices(client, run_id, run_date)


if __name__ == "__main__":
    main()
