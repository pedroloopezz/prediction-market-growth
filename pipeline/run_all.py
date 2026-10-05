"""Reproduce everything from the public API with one command.

    python -m pipeline.run_all            # ingest (incremental) -> warehouse -> analysis -> tests
    python -m pipeline.run_all --skip-ingest   # rebuild from the raw Parquet already on disk

A first run takes ~2.5 hours, almost all of it rate-limited API calls (Manifold allows 500
requests/minute; we stay at <= 400). Later runs only fetch what is missing.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys

STEPS = [
    ("ingest: market snapshot", [sys.executable, "-m", "pipeline.ingest.run", "markets"]),
    ("ingest: full markets", [sys.executable, "-m", "pipeline.ingest.run", "full"]),
    ("ingest: pre-close prices", [sys.executable, "-m", "pipeline.ingest.run", "prices"]),
    ("warehouse: build", [sys.executable, "-m", "pipeline.warehouse.build"]),
    ("analysis: growth", [sys.executable, "-m", "pipeline.analysis.demand"]),
    ("analysis: pricing", [sys.executable, "-m", "pipeline.analysis.calibration"]),
    ("analysis: slide charts", [sys.executable, "-m", "pipeline.analysis.slides"]),
    # last, so the memo-vs-results check runs against the numbers just produced
    ("tests: parsers, data quality, reported numbers", [sys.executable, "-m", "pytest", "-q"]),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-ingest", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for name, cmd in STEPS:
        if args.skip_ingest and name.startswith("ingest"):
            continue
        logging.info("==> %s", name)
        subprocess.run(cmd, check=True)
    logging.info("done")


if __name__ == "__main__":
    main()
