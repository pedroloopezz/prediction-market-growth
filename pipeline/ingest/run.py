"""Ingest Manifold markets into raw Parquet.

    python -m pipeline.ingest.run markets          # snapshot of every lite market
    python -m pipeline.ingest.run full --since 2025-09-01   # full markets (topics, answers)

Layout:  data/raw/<dataset>/run_date=YYYY-MM-DD/part-*.parquet
Every run writes a manifest with its run_id and row counts to data/raw/_runs/.

Idempotency:
  * markets: one snapshot per run date. Re-running the same day is a no-op unless --force.
  * full:    incremental. Market ids already present in any markets_full partition are skipped,
             and results are flushed in chunks so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.config import RAW_DIR
from pipeline.ingest.manifold_client import ManifoldClient
from pipeline.ingest.models import FullMarket, LiteMarket, full_row, lite_row, pandas_dtypes

log = logging.getLogger("ingest")

# Polls and bounties are not tradable markets, so they never enter the warehouse.
NON_MARKET_TYPES = ("POLL", "BOUNTIED_QUESTION")
FULL_CHUNK = 500
FULL_WORKERS = 4


def _partition(dataset: str, run_date: str) -> Path:
    return RAW_DIR / dataset / f"run_date={run_date}"


LITE_DTYPES = {**pandas_dtypes(LiteMarket), "raw_json": "string"}
FULL_DTYPES = {**pandas_dtypes(FullMarket), "n_answers": "Int64", "raw_json": "string"}


def _write(
    rows: list[dict], path: Path, run_id: str, fetched_at: str, dtypes: dict[str, str]
) -> None:
    df = pd.DataFrame(rows).astype(dtypes)
    df["run_id"] = run_id
    df["fetched_at"] = fetched_at
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _manifest(run_id: str, dataset: str, counts: dict) -> None:
    out = RAW_DIR / "_runs" / f"{run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"run_id": run_id, "dataset": dataset, **counts}, indent=2))
    log.info("run %s %s: %s", run_id, dataset, counts)


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
        _write(
            [lite_row(m) for m in page],
            tmp / f"part-{i:04d}.parquet",
            run_id,
            fetched_at,
            LITE_DTYPES,
        )
        n += len(page)
        if i % 25 == 0:
            log.info("page %d: %d markets so far", i, n)
    # swap in atomically so a crash never leaves a half-written snapshot behind
    shutil.rmtree(part, ignore_errors=True)
    tmp.rename(part)
    _manifest(run_id, "markets_lite", {"rows": n, "requests": client.n_requests})


def _candidate_ids(since_ms: int) -> list[str]:
    """Resolved, tradable markets resolved on/after `since`, from the latest lite snapshot."""
    latest = sorted((RAW_DIR / "markets_lite").glob("run_date=*"))[-1]
    con = duckdb.connect()
    ids = con.execute(
        f"""
        SELECT id FROM read_parquet('{latest}/*.parquet')
        WHERE is_resolved AND resolution_time >= ? AND outcome_type NOT IN {NON_MARKET_TYPES}
        ORDER BY resolution_time DESC
        """,
        [since_ms],
    ).fetchall()
    return [r[0] for r in ids]


def _already_fetched() -> set[str]:
    files = list((RAW_DIR / "markets_full").glob("run_date=*/*.parquet"))
    if not files:
        return set()
    con = duckdb.connect()
    rows = con.execute("SELECT DISTINCT id FROM read_parquet(?)", [[str(f) for f in files]])
    return {r[0] for r in rows.fetchall()}


def ingest_full(client: ManifoldClient, run_id: str, run_date: str, since: str) -> None:
    since_ms = int(datetime.fromisoformat(since).replace(tzinfo=UTC).timestamp() * 1000)
    candidates = _candidate_ids(since_ms)
    done = _already_fetched()
    todo = [i for i in candidates if i not in done]
    log.info(
        "full markets: %d candidates, %d already fetched, %d to fetch",
        len(candidates),
        len(candidates) - len(todo),
        len(todo),
    )
    part = _partition("markets_full", run_date)
    fetched_at = datetime.now(UTC).isoformat()

    def fetch(market_id: str) -> dict | None:
        try:
            return full_row(client.get_market(market_id))
        except Exception as exc:  # deleted/private market: log and move on
            log.warning("market %s skipped: %s", market_id, exc)
            return None

    n_written = n_missing = 0
    # A few threads hide network latency; the client's lock still enforces the global rate limit.
    with ThreadPoolExecutor(max_workers=FULL_WORKERS) as pool:
        for chunk_no, start in enumerate(range(0, len(todo), FULL_CHUNK)):
            results = list(pool.map(fetch, todo[start : start + FULL_CHUNK]))
            rows = [r for r in results if r is not None]
            n_missing += len(results) - len(rows)
            if rows:
                name = f"part-{run_id}-{chunk_no:04d}.parquet"
                _write(rows, part / name, run_id, fetched_at, FULL_DTYPES)
                n_written += len(rows)
            log.info("full markets: %d / %d fetched", start + len(results), len(todo))
    _manifest(
        run_id,
        "markets_full",
        {
            "since": since,
            "candidates": len(candidates),
            "fetched_this_run": n_written,
            "skipped_errors": n_missing,
            "requests": client.n_requests,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="dataset", required=True)
    m = sub.add_parser("markets")
    m.add_argument("--force", action="store_true")
    f = sub.add_parser("full")
    f.add_argument("--since", default="2025-09-01", help="resolution date lower bound (UTC)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    now = datetime.now(UTC)
    run_id = f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    run_date = f"{now:%Y-%m-%d}"
    with ManifoldClient() as client:
        if args.dataset == "markets":
            ingest_markets(client, run_id, run_date, args.force)
        else:
            ingest_full(client, run_id, run_date, args.since)


if __name__ == "__main__":
    main()
