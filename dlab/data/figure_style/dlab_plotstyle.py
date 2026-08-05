"""
decision-lab figure style helpers for matplotlib.

The global look (palette cycle, Inter, near-black furniture, clean spines,
white marker edges) lives in ``_style/matplotlibrc``, which dlab activates via
the MATPLOTLIBRC environment variable — it applies whether or not this module
is imported. This module adds the pieces an rc file cannot express:

    import dlab_plotstyle  # noqa: F401

On import it forces ``fill_between`` / ``fill_betweenx`` edges to ``"none"``
— bands never carry an outline in this style, so edge/linewidth kwargs are
dropped even when passed explicitly (e.g. by arviz or pymc-marketing HDI
plots). It also exposes the palette by name and an axis end-cap helper:

    from dlab_plotstyle import PALETTE, PALETTE_LIGHT, PALETTE_DARK
    from dlab_plotstyle import add_axis_end_tick_caps

Adapted from the PyMC Labs report template (pymclabsreport) with the
decision-lab palette.
"""

import functools

import matplotlib as _mpl
import matplotlib.axes as _maxes
import matplotlib.figure as _mfigure
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D

# Base palette, in the same fixed order as the matplotlibrc color cycle.
# The adjacency order is CVD-validated — reference series colors by name and
# let the cycle assign order-free series.
PALETTE = {
    "pine": "#007D5F",
    "coral": "#E87A69",
    "sky": "#50B1DC",
    "petrol": "#136A94",
    "leaf": "#4E9A5B",
    "sand": "#CCAE59",
    "plum": "#7D4778",
    "olive": "#808F3B",
}
# Variants for shading and emphasis: light for filled bands and backgrounds
# (55% toward white), dark for emphasis and outlines (35% toward black).
PALETTE_LIGHT = {
    "pine": "#8CC5B7",
    "coral": "#F5C3BB",
    "sky": "#B0DCEF",
    "petrol": "#95BCCF",
    "leaf": "#AFD2B5",
    "sand": "#E8DBB4",
    "plum": "#C5ACC2",
    "olive": "#C6CDA7",
}
PALETTE_DARK = {
    "pine": "#00513E",
    "coral": "#974F44",
    "sky": "#34738F",
    "petrol": "#0C4560",
    "leaf": "#33643B",
    "sand": "#85713A",
    "plum": "#512E4E",
    "olive": "#535D26",
}

# Furniture color matching the rc: near-black for axes, labels, and titles.
INK = "#333333"
TITLE_INK = INK


def _register_colormaps():
    # House colormaps, registered so cmap="dlab_div" / cmap="dlab_seq" work
    # everywhere. dlab_div (pine <-> coral, soft-white midpoint) is for signed
    # data (correlations, deltas); dlab_seq (soft-white -> deep pine) is for
    # magnitudes and becomes the default image colormap.
    div = LinearSegmentedColormap.from_list(
        "dlab_div",
        [PALETTE_DARK["pine"], PALETTE["pine"], "#F7F7F7",
         PALETTE["coral"], PALETTE_DARK["coral"]],
    )
    seq = LinearSegmentedColormap.from_list(
        "dlab_seq",
        ["#F7F7F7", PALETTE_LIGHT["pine"], PALETTE["pine"], PALETTE_DARK["pine"]],
    )
    _mpl.colormaps.register(div, force=True)
    _mpl.colormaps.register(seq, force=True)
    _mpl.rcParams["image.cmap"] = "dlab_seq"


def _patch_fill_between():
    # Bands never carry an outline in this style, period — the edge kwargs are
    # dropped even when passed explicitly (libraries like arviz/pymc-marketing
    # outline their HDI bands), then edgecolor is forced to "none".
    for name in ("fill_between", "fill_betweenx"):
        orig = getattr(_maxes.Axes, name)
        if getattr(orig, "_dlab_patched", False):
            continue

        def _wrap(orig):
            @functools.wraps(orig)
            def wrapper(self, *args, **kwargs):
                for key in ("edgecolor", "edgecolors", "ec", "linewidth",
                            "linewidths", "lw"):
                    kwargs.pop(key, None)
                kwargs["edgecolor"] = "none"
                return orig(self, *args, **kwargs)

            wrapper._dlab_patched = True
            return wrapper

        setattr(_maxes.Axes, name, _wrap(orig))


def _patch_frameless_legends():
    # Legends are frameless in this style, period. Agents habitually pass
    # frameon=True, so this is enforced rather than defaulted: the kwarg is
    # dropped (rc legend.frameon=False then applies).
    for cls in (_maxes.Axes, _mfigure.FigureBase):
        orig = cls.legend
        if getattr(orig, "_dlab_patched", False):
            continue

        def _wrap(orig):
            @functools.wraps(orig)
            def wrapper(self, *args, **kwargs):
                kwargs.pop("frameon", None)
                return orig(self, *args, **kwargs)

            wrapper._dlab_patched = True
            return wrapper

        cls.legend = _wrap(orig)


def _patch_suptitle_ink():
    # figure.titlesize/titleweight are rc keys, but suptitle color is not —
    # default it to the title ink so suptitles match axes titles.
    orig = _mfigure.FigureBase.suptitle
    if getattr(orig, "_dlab_patched", False):
        return

    @functools.wraps(orig)
    def wrapper(self, *args, **kwargs):
        kwargs.setdefault("color", TITLE_INK)
        return orig(self, *args, **kwargs)

    wrapper._dlab_patched = True
    _mfigure.FigureBase.suptitle = wrapper


def _patch_boxless_text():
    # Boxed annotations (bbox=dict(...) around text) are forbidden in this
    # style: the box competes with the data. The bbox kwarg is dropped.
    for name in ("text", "annotate"):
        orig = getattr(_maxes.Axes, name)
        if getattr(orig, "_dlab_patched", False):
            continue

        def _wrap(orig):
            @functools.wraps(orig)
            def wrapper(self, *args, **kwargs):
                kwargs.pop("bbox", None)
                return orig(self, *args, **kwargs)

            wrapper._dlab_patched = True
            return wrapper

        setattr(_maxes.Axes, name, _wrap(orig))


_register_colormaps()
_patch_fill_between()
_patch_frameless_legends()
_patch_boxless_text()
_patch_suptitle_ink()


def add_axis_end_tick_caps(ax, x=True, y=True, which="major"):
    """Add endpoint caps matching the ticks at each spine's open end.

    When a continuous axis is fitted to the data, its spine often stops
    between two labeled ticks, which reads as if the axis ran out of room.
    This draws a small cap matching the real ticks at each spine's open end,
    so the axis reads as bounded without adding a fake tick or gridline.
    Call it after limits, ticks, and spines are set (it re-syncs on limit and
    draw events). Pass ``y=False`` for hidden or categorical y-axes.

    Returns the list of cap ``Line2D`` artists.
    """
    tick_getter = {
        "major": lambda axis: axis.get_major_ticks(),
        "minor": lambda axis: axis.get_minor_ticks(),
    }[which]

    # Spine layout: which side each axis lives on.
    y_right = ax.spines["right"].get_visible() and not ax.spines["left"].get_visible()
    x_top = ax.spines["top"].get_visible() and not ax.spines["bottom"].get_visible()
    x_attr = "tick2line" if x_top else "tick1line"
    y_attr = "tick2line" if y_right else "tick1line"
    x_which = "tick2" if x_top else "tick1"
    y_which = "tick2" if y_right else "tick1"
    x_frac = 1.0 if x_top else 0.0
    y_frac = 1.0 if y_right else 0.0

    def tickline(axis, attr):
        for tick in tick_getter(axis):
            line = getattr(tick, attr)
            if line.get_visible():
                return line
        ticks = tick_getter(axis)
        return getattr(ticks[0], attr) if ticks else None

    def style_cap(dst, src):
        dst.update_from(src)
        dst.set_clip_on(False)
        dst.set_label("_nolegend_")

    def has_tick(axis_obj, bound):
        locs = (axis_obj.get_majorticklocs() if which == "major"
                else axis_obj.get_minorticklocs())
        return np.any(np.isclose(locs, bound))

    xcap = Line2D([], [])
    ycap = Line2D([], [])
    caps = []
    if x:
        ax.add_artist(xcap)
        caps.append(xcap)
    if y:
        ax.add_artist(ycap)
        caps.append(ycap)

    def sync(_=None):
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()

        if x:
            # open end of the x-axis: the end away from the y-axis
            x_end = xmin if y_right else xmax
            if has_tick(ax.xaxis, x_end):
                xcap.set_visible(False)
            else:
                src = tickline(ax.xaxis, x_attr)
                if src is not None:
                    style_cap(xcap, src)
                    xcap.set_data([x_end], [x_frac])
                    xcap.set_transform(ax.get_xaxis_transform(which=x_which))
                    xcap.set_visible(True)

        if y:
            # top of the y-axis, on whichever side it is drawn
            if has_tick(ax.yaxis, ymax):
                ycap.set_visible(False)
            else:
                src = tickline(ax.yaxis, y_attr)
                if src is not None:
                    style_cap(ycap, src)
                    ycap.set_data([y_frac], [ymax])
                    ycap.set_transform(ax.get_yaxis_transform(which=y_which))
                    ycap.set_visible(True)

    sync()

    ax.callbacks.connect("xlim_changed", sync)
    ax.callbacks.connect("ylim_changed", sync)
    ax.figure.canvas.mpl_connect("draw_event", sync)

    return caps
