---
name: dlab-figure-style
description: decision-lab house figure style for matplotlib. Use whenever creating, styling, or saving any matplotlib figure, chart, or plot. The environment is already styled — this skill covers only the rules the style config cannot enforce.
---

# decision-lab figure style

The session environment already styles every matplotlib figure (palette color
cycle, fonts, clean spines, marker edges, legend, figure size) via an rc file
activated through the MATPLOTLIBRC environment variable. Your job is to NOT
undo that, and to follow the few rules the rc cannot enforce.

## Never override the house style

- NEVER call `sns.set_theme()`, `sns.set()`, `sns.set_style()`, or
  `plt.style.use(...)` — one such call silently destroys the entire house
  style. If you use seaborn, import it plainly (`import seaborn as sns`) and
  pass colors/axes explicitly; do not apply its themes.
- Do NOT set fonts, spine visibility, furniture colors, grid style, or
  `rcParams` in plotting scripts. The environment already did.
- Do NOT hard-code hex colors or CSS color names (`"red"`, `"tab:blue"`).
  Colors come from the palette (below) or from the default cycle.

## Use the palette by name

```python
import dlab_plotstyle  # activates clean fill_between edges; always import it
from dlab_plotstyle import PALETTE, PALETTE_LIGHT, PALETTE_DARK
```

- For order-free multi-series plots, pass no colors at all — the default
  cycle assigns well-separated, colorblind-safe colors in a validated order.
- Set a color explicitly only when a series has fixed meaning across figures
  (the same channel/category in every exhibit), and take it from `PALETTE`.
- Use `PALETTE_LIGHT` for filled bands and backgrounds, `PALETTE_DARK` for
  emphasis and outlines.

## The rules the rc cannot enforce

1. **Scatter edge trap.** `ax.scatter(..., color=X)` sets face AND edge to X,
   silently cancelling the thin white marker edge. For colored markers pass
   `edgecolor="white", linewidth=0.6` explicitly; for white/open markers use
   `facecolor="white", edgecolor=PALETTE_LIGHT["petrol"], linewidth=0.9`.
2. **Band/line layering.** Draw each series' `fill_between` one z-layer below
   its own line (`zorder=2*i` for the fill, `2*i+1` for the line), reference
   lines (`axhline`/`axvline`) on top.
3. **Grid OR reference lines — never both.** A panel gets either a subtle
   grid (`ax.grid(True)`) or explicit reference lines (`axhline`/`axvline`
   for bounds, quartiles, thresholds), never the two together. If you draw
   reference lines, turn the grid off for that panel.
4. **Legends are frameless and text is boxless.** Never pass `frameon=True`
   to `legend()` and never wrap text/annotations in a `bbox` box (both are
   stripped by the environment anyway). Keep legends at their default size.
5. **Axis limits.** On continuous scatter/line panels, fit limits to the data
   (`ax.set_xlim(x.min(), x.max())`), then call
   `dlab_plotstyle.add_axis_end_tick_caps(ax)` so fitted spine ends read as
   bounded. Leave padding alone on categorical axes, bars, and distributions.
6. **One legend per exhibit.** In multi-panel figures, use one shared legend
   for the whole figure, not a repeated per-panel legend. Never label every
   data point — direct-label selectively.
7. **Low-contrast series need labels.** Coral, sky, and sand sit below 3:1
   contrast on white — when one carries a key series, add a direct label or
   annotation so identity never rides on color alone.
8. **Scatter with many categories.** Only the first three cycle colors are
   mutually distinguishable in unordered point clouds. For scatter plots with
   more than 3 categories, add marker shapes or facet into small multiples.
9. **Heatmaps and images.** Use the registered house colormaps: `dlab_seq`
   (the default) for magnitudes, `cmap="dlab_div"` for signed data such as
   correlations or deltas. Never use jet, rainbow, or viridis.

## Before finishing

Audit your plotting scripts programmatically — do not eyeball:

```bash
grep -nE "set_theme|set_style|plt\.style\.use|frameon=True|bbox=dict|color=[\"']#|color=[\"'](red|blue|green|orange|purple|tab:)" *.py
```

Any hit is a violation: replace with palette names or the default cycle.
