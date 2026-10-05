"""Three slide-ready charts, one per memo recommendation, built only from reports/results.json.

    python -m pipeline.analysis.slides     (run after demand and calibration)

Consulting style: the title states the takeaway, a one-line subtitle says what is plotted,
a source line sits at the bottom. 16:9 at 200 dpi.
"""

from __future__ import annotations

import json
import logging

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

from pipeline.analysis.common import (
    BLUE,
    MUTED,
    RESULTS_PATH,
    SURFACE,
    TEXT,
    TEXT_2,
    source_line,
)
from pipeline.config import FIGURES_DIR, REPORTS_DIR

log = logging.getLogger("slides")


def slide(height_ratio: float = 0.5625) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(10, 10 * height_ratio), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=TEXT_2, labelsize=11, length=0)
    return fig, ax


def finish(
    fig: plt.Figure,
    title: str,
    subtitle: str,
    source: str,
    name: str,
    left: float = 0.2,
    note: str | None = None,
) -> str:
    fig.text(0.03, 0.93, title, fontsize=17, fontweight="bold", color=TEXT, ha="left")
    fig.text(0.03, 0.875, subtitle, fontsize=11, color=TEXT_2, ha="left")
    if note:
        fig.text(0.03, 0.075, note, fontsize=10, color=TEXT, ha="left", style="italic")
    fig.text(0.03, 0.025, source, fontsize=8.5, color=TEXT_2, ha="left")
    fig.subplots_adjust(left=left, right=0.96, top=0.8, bottom=0.2 if note else 0.16)
    path = FIGURES_DIR / f"{name}.png"
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return str(path.relative_to(REPORTS_DIR.parent))


def slide_long_tail(g: dict) -> str:
    """Rec 1: the bottom 64% of listings produce ~20% of trader participation."""
    c = g["concentration"]["overall"]["traders"]
    head = c["share_of_markets_for_80pct"]
    tail_share = c["bottom_64pct_share"]
    fig, ax = slide()
    rows = [("Trader participation", 1 - tail_share, tail_share), ("Listings", head, 1 - head)]
    for y, (_label, top, bottom) in enumerate(rows):
        ax.barh(y, top, height=0.55, color=BLUE)
        ax.barh(y, bottom, left=top, height=0.55, color=MUTED)
        ax.text(
            top / 2,
            y,
            f"{top:.0%}",
            ha="center",
            va="center",
            color="white",
            fontsize=15,
            fontweight="bold",
        )
        ax.text(
            top + bottom / 2,
            y,
            f"{bottom:.0%}",
            ha="center",
            va="center",
            color=TEXT,
            fontsize=15,
            fontweight="bold",
        )
    ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=12, color=TEXT)
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.legend(
        handles=[
            Patch(color=BLUE, label=f"Top {head:.0%} of listings"),
            Patch(color=MUTED, label=f"Bottom {1 - head:.0%} of listings"),
        ],
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.02),
        ncol=2,
        fontsize=11,
    )
    dead = g["concentration"]["zero_trader_markets"]
    return finish(
        fig,
        f"The bottom {1 - head:.0%} of listings generate only {tail_share:.0%} of participation",
        f"Markets ranked by unique traders; {dead:,} listings "
        f"({g['concentration']['zero_trader_share']:.1%}) drew no traders at all",
        source_line(g["n_markets"]),
        "slide_1_long_tail",
    )


def slide_creators(g: dict) -> str:
    """Rec 2: markets from creators with a strong track record draw far more traders."""
    t = g["creator_track_record"]
    q = t["quintiles"]
    med = np.array([r["median_traders"] for r in q])
    fig, ax = slide()
    x = np.arange(len(q))
    ax.bar(x, med, width=0.62, color=[MUTED] * (len(q) - 1) + [BLUE])
    for xi, m in zip(x, med, strict=True):
        ax.text(xi, m + 0.4, f"{m:.0f}", ha="center", fontsize=14, fontweight="bold", color=TEXT)
    labels = [f"{r['track_record_quintile'].split(' ')[0]}\n{r['track_record_range']}" for r in q]
    ax.set_xticks(x, labels, fontsize=10.5)
    ax.set_yticks([])
    ax.set_xlabel(
        "Creator track record quintile (avg traders on the creator's earlier, closed markets)",
        color=TEXT_2,
        fontsize=10.5,
    )
    ratio = med[-1] / med[0]
    return finish(
        fig,
        f"Top track-record creators draw {ratio:.1f}x the traders of the weakest",
        f"Median unique traders per market; regression: +{t['doubling_track_record_pct']:.0%} "
        f"traders per doubling of track record (n = {t['n']:,})",
        source_line(g["n_markets"]),
        "slide_2_creators",
        left=0.04,
    )


def slide_listing_plan(g: dict, p: dict) -> str:
    """Rec 3: rebalance the first 100 listings toward under-served demand."""
    plan = sorted(g["listing_plan"]["plan"], key=lambda r: r["plan_first_100"])
    fig, ax = slide()
    y = np.arange(len(plan))
    h = 0.38
    cur = [r["current_per_100"] for r in plan]
    new = [r["plan_first_100"] for r in plan]
    ax.barh(y + h / 2, cur, h, color=MUTED)
    ax.barh(y - h / 2, new, h, color=BLUE)
    for yi, (a, b) in enumerate(zip(cur, new, strict=True)):
        ax.text(a + 0.3, yi + h / 2, f"{a}", va="center", fontsize=10, color=TEXT_2)
        ax.text(
            b + 0.3, yi - h / 2, f"{b}", va="center", fontsize=11, color=TEXT, fontweight="bold"
        )
    ax.set_yticks(y, [r["category"] for r in plan], fontsize=12, color=TEXT)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.grid(False)
    ax.legend(
        handles=[
            Patch(color=MUTED, label="Manifold today, per 100 listings"),
            Patch(color=BLUE, label="Proposed first 100 listings"),
        ],
        frameon=False,
        loc="lower right",
        fontsize=10.5,
    )
    gains = sorted((r for r in plan if r["change"] > 0), key=lambda r: -r["change"])
    gain_txt = ", ".join(f"+{r['change']} {r['category']}" for r in gains)
    acc = {r["trader_bin"]: r["brier"] for r in p["slope_by_traders"]}
    moved = g["listing_plan"]["listings_moved_per_100"]
    return finish(
        fig,
        f"Shift {moved:.0f} of every 100 listings toward under-served demand",
        f"{gain_txt}. Shelf share = each category's share of unique traders (floor 3)",
        source_line(g["n_markets"]),
        "slide_3_listing_plan",
        note=f"Why concentrate: markets with 50+ traders are also the most accurate "
        f"(Brier {acc['50+']:.3f} vs {acc['10-19']:.3f} for 10-19 traders; lower is better)",
    )


def run() -> dict:
    r = json.loads(RESULTS_PATH.read_text())
    g, p = r["growth"], r["pricing"]
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "rec1_long_tail": slide_long_tail(g),
        "rec2_creators": slide_creators(g),
        "rec3_listing_plan": slide_listing_plan(g, p),
    }
    log.info("slides: %s", list(out.values()))
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
