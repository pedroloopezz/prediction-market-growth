"""Paths and constants shared across the pipeline."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"
SAMPLES_DIR = ROOT / "samples"
REPORTS_DIR = ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

MANIFOLD_BASE_URL = "https://api.manifold.markets/v0"
# Manifold allows 500 requests/minute per IP. 0.15 s between calls caps us at 400/min.
MIN_SECONDS_BETWEEN_REQUESTS = 0.15
