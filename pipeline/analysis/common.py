"""Shared helpers for the analysis scripts: data access, chart style, results.json."""

from __future__ import annotations

import json
from typing import Any

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pipeline.config import (  # noqa: E402
    FIGURES_DIR,
    REPORTS_DIR,
    WAREHOUSE_PATH,
    WINDOW_END,
    WINDOW_START,
)

RESULTS_PATH = REPORTS_DIR / "results.json"

# Manifold-specific or unclassifiable buckets: always shown, always visually separate, never
# used for the listing recommendation of a real-money exchange.
NON_EXCHANGE_CATEGORIES = ["Personal / Manifold-meta", "Uncategorized"]

# Chart palette (validated reference palette, light mode): two categorical slots + neutrals.
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
MUTED = "#b5b4ae"
BLUE = "#2a78d6"
ORANGE = "#eb6834"


def load_mart() -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    df = con.execute("SELECT * FROM mart_market_outcomes").df()
    con.close()
    return df


def source_line(n: int) -> str:
    return (
        f"Source: Manifold Markets public API, markets resolved {WINDOW_START} to "
        f"{pd.Timestamp(WINDOW_END) - pd.Timedelta(days=1):%Y-%m-%d} (n = {n:,}). "
        "Play-money platform."
    )


def style_axes(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=TEXT_2, labelsize=9, length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def new_figure(width: float = 8.0, height: float = 4.8) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(width, height), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    style_axes(ax)
    return fig, ax


def finish_figure(fig: plt.Figure, title: str, subtitle: str, source: str, name: str) -> str:
    """Takeaway title, one-line subtitle, source line at the bottom; save as PNG."""
    fig.suptitle(title, x=0.02, y=0.98, ha="left", fontsize=13, fontweight="bold", color=TEXT)
    fig.text(0.02, 0.915, subtitle, ha="left", fontsize=9.5, color=TEXT_2)
    fig.text(0.02, 0.015, source, ha="left", fontsize=7.5, color=TEXT_2)
    fig.tight_layout(rect=(0, 0.04, 1, 0.9))
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / f"{name}.png"
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return str(path.relative_to(REPORTS_DIR.parent))


def _jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating | float):
        return None if np.isnan(x) else round(float(x), 4)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def write_results(section: str, payload: dict) -> None:
    """Replace one top-level section of reports/results.json, keeping the others."""
    results = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else {}
    results[section] = _jsonable(payload)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n")
