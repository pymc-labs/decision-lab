"""
Deterministic proofsheet for the decision-lab figure style.

Renders every chart archetype the style guidelines cover — same data, same
seed, every run — so style changes (rc, dlab_plotstyle, palette) can be
iterated visually: edit dlab/data/figure_style/, rerun, compare.

    ~/miniconda3/envs/dlab-testing/bin/python scripts/figure_style_gallery.py [OUT.png]

Some panels deliberately attempt forbidden styling (frameon=True legends,
bbox-boxed annotations, a plain suptitle) to prove the dlab_plotstyle
enforcement strips them — if a legend frame or text box ever shows up in the
proofsheet, enforcement is broken.
"""

import sys
from pathlib import Path

import matplotlib

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
STYLE_DIR: Path = REPO_ROOT / "dlab" / "data" / "figure_style"

matplotlib.use("Agg")
matplotlib.rc_file(STYLE_DIR / "matplotlibrc")
sys.path.insert(0, str(STYLE_DIR))

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import dlab_plotstyle  # noqa: E402,F401  — applies the enforcement patches
from dlab_plotstyle import (  # noqa: E402
    PALETTE,
    PALETTE_DARK,
    PALETTE_LIGHT,
    add_axis_end_tick_caps,
)


def main(out_path: str, heatmap_cmap: object = "dlab_div", label: str = "") -> None:
    rng = np.random.default_rng(42)
    x = np.linspace(0.0, 10.0, 60)
    keys = list(PALETTE)

    fig, axes = plt.subplots(4, 3, figsize=(13.5, 13.5))

    # -- 1: full color cycle on lines with markers
    ax = axes[0, 0]
    for i in range(8):
        ax.plot(x, np.sin(x + 0.5 * i) + 0.6 * i, marker="o", ms=3.5, markevery=6)
    ax.set_title("Cycle: 8 series, lines + markers")
    ax.set_xlabel("time")
    ax.set_ylabel("value")

    # -- 2: palette swatches (base / light / dark) with names
    ax = axes[0, 1]
    for c, k in enumerate(keys):
        for r, pal in enumerate((PALETTE_DARK, PALETTE, PALETTE_LIGHT)):
            ax.add_patch(plt.Rectangle((c, r), 0.92, 0.92, color=pal[k]))
        ax.text(c + 0.46, -0.25, k, ha="center", va="top", fontsize=6.5, rotation=45)
    ax.set_xlim(-0.2, 8.2)
    ax.set_ylim(-1.6, 3.2)
    ax.axis("off")
    ax.set_title("Palette: dark / base / light")

    # -- 3: band + line + reference line (grid off: rule 3), axis caps
    ax = axes[0, 2]
    mean = np.sin(x) * np.exp(-x / 8.0)
    band = 0.3 + 0.1 * np.sqrt(x)
    ax.fill_between(x, mean - band, mean + band, color=PALETTE_LIGHT[keys[0]], alpha=0.7, zorder=0)
    ax.plot(x, mean, color=PALETTE[keys[0]], zorder=1)
    ax.axhline(0.0, color="#333333", ls="--", lw=0.8, zorder=2)
    ax.set_xlim(x.min(), x.max())
    add_axis_end_tick_caps(ax)
    ax.set_title("Band + line + reference (no grid)")
    ax.set_xlabel("time")

    # -- 4: scatter, three all-pairs-safe categories, white edges
    ax = axes[1, 0]
    for k in keys[:3]:
        pts = rng.normal(loc=rng.uniform(-1.5, 1.5, 2), scale=0.6, size=(60, 2))
        ax.scatter(pts[:, 0], pts[:, 1], color=PALETTE[k], edgecolor="white",
                   linewidth=0.6, s=22, label=k)
    # deliberately forbidden: frameon must be stripped by the patch
    ax.legend(frameon=True)
    ax.set_title("Scatter: 3 categories, frameless legend")

    # -- 5: bars from the cycle + direct value labels
    ax = axes[1, 1]
    vals = rng.uniform(1.0, 5.0, 5)
    names = [f"ch {c}" for c in "ABCDE"]
    ax.bar(names, vals, color=[PALETTE[k] for k in keys[:5]])
    for i, v in enumerate(vals):
        ax.text(i, v + 0.12, f"{v:.1f}", ha="center", fontsize=7)
    ax.set_title("Bars + direct labels")
    ax.set_ylabel("effect")

    # -- 6: stacked area
    ax = axes[1, 2]
    parts = np.abs(rng.normal(1.0, 0.3, (4, 60))) + 0.3
    ax.stackplot(x, parts, labels=keys[:4], colors=[PALETTE[k] for k in keys[:4]])
    ax.legend(loc="upper left", ncol=2)
    ax.set_xlim(x.min(), x.max())
    ax.set_title("Stacked area")

    # -- 7: histogram + kde-ish line
    ax = axes[2, 0]
    sample = rng.normal(0.0, 1.0, 400)
    ax.hist(sample, bins=24, color=PALETTE_LIGHT[keys[0]], edgecolor="white", linewidth=0.5)
    ax.axvline(float(np.median(sample)), color=PALETTE_DARK[keys[0]], ls="--", lw=1.0)
    ax.set_title("Histogram + median line")

    # -- 8: boxplots per category
    ax = axes[2, 1]
    data = [rng.normal(mu, 0.8, 80) for mu in (0.0, 0.8, 1.6, 1.2)]
    bp = ax.boxplot(data, tick_labels=[f"g{i}" for i in range(1, 5)], patch_artist=True)
    for patch, k in zip(bp["boxes"], keys[:4]):
        patch.set_facecolor(PALETTE_LIGHT[k])
        patch.set_edgecolor(PALETTE_DARK[k])
    ax.set_title("Boxplots")

    # -- 9: diverging heatmap + colorbar
    ax = axes[2, 2]
    mat = np.corrcoef(rng.normal(0.0, 1.0, (5, 40)) + 0.4 * rng.normal(0.0, 1.0, (1, 40)))
    im = ax.imshow(mat, cmap=heatmap_cmap, vmin=-1.0, vmax=1.0)
    for i in range(5):
        for j in range(5):
            ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center", fontsize=6.5,
                    color="white" if abs(mat[i, j]) > 0.6 else "#333333")
    ax.set_xticks(range(5), [f"v{i}" for i in range(5)])
    ax.set_yticks(range(5), [f"v{i}" for i in range(5)])
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title("Correlation heatmap")

    # -- 10: annotation — bbox deliberately passed, must render boxless
    ax = axes[3, 0]
    pts = rng.normal(0.0, 1.0, (80, 2))
    pts[:, 1] = 0.5 * pts[:, 0] + rng.normal(0.0, 0.7, 80)
    ax.scatter(pts[:, 0], pts[:, 1], color=PALETTE[keys[0]], edgecolor="white", linewidth=0.6, s=20)
    r = float(np.corrcoef(pts[:, 0], pts[:, 1])[0, 1])
    ax.annotate(f"r = {r:.3f}", xy=(0.05, 0.92), xycoords="axes fraction",
                fontsize=8, color=PALETTE_DARK[keys[0]],
                bbox=dict(boxstyle="round", fc="white", ec="black"))
    ax.set_title("Annotation (box stripped)")

    # -- 11: grid-only panel (rule 3, the other branch)
    ax = axes[3, 1]
    for k in keys[:2]:
        ax.plot(x, np.cumsum(rng.normal(0.1, 0.5, 60)), color=PALETTE[k], label=k)
    ax.grid(True)
    ax.legend()
    ax.set_xlim(x.min(), x.max())
    ax.set_title("Grid only (no reference lines)")

    # -- 12: rolling mean over de-emphasized raw series
    ax = axes[3, 2]
    raw = np.cumsum(rng.normal(0.0, 1.0, 120)) + 50.0
    roll = np.convolve(raw, np.ones(8) / 8.0, mode="valid")
    ax.plot(raw, color=PALETTE_LIGHT[keys[0]], lw=1.0, label="weekly")
    ax.plot(np.arange(7, 120), roll, color=PALETTE[keys[1]], lw=1.6, label="8w avg")
    ax.legend()
    ax.set_title("Raw (light) + rolling mean")

    title = "decision-lab figure style — deterministic proofsheet"
    if label:
        title += f" — {label}"
    fig.suptitle(title)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.98))
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "figure_style_gallery.png")
