"""
Tests for mmm_lib's integration with the decision-lab figure style.

The contract: mmm_lib must work (and not restyle matplotlib) outside dlab
sessions where ``dlab_plotstyle`` is absent, and its correlation heatmap must
prefer the house diverging colormap ``dlab_div`` whenever a colormap by that
name is registered.
"""

import os
import subprocess
import sys

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from mmm_lib.data_preparation import plot_correlation_heatmap  # noqa: E402


def _heatmap_cmap_name(df: pd.DataFrame) -> str:
    """Render the correlation heatmap and return the image's colormap name."""
    fig = plot_correlation_heatmap(df)
    ax = fig.axes[0]
    name: str = ax.images[0].get_cmap().name
    plt.close(fig)
    return name


def test_import_without_dlab_plotstyle_does_not_restyle() -> None:
    """Standalone import works and leaves matplotlib's style untouched."""
    env = dict(os.environ)
    # Ensure dlab_plotstyle is NOT importable (strip any session _style path)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in env.get("PYTHONPATH", "").split(os.pathsep)
        if p and not p.endswith("_style")
    ) or "/opt"
    env.pop("MATPLOTLIBRC", None)
    result = subprocess.run(
        [sys.executable, "-c", (
            "import importlib.util, matplotlib\n"
            "matplotlib.use('Agg')\n"
            "assert importlib.util.find_spec('dlab_plotstyle') is None, "
            "'test precondition: dlab_plotstyle must be absent'\n"
            "import mmm_lib\n"
            "cycle = matplotlib.rcParams['axes.prop_cycle'].by_key()['color']\n"
            "assert cycle[0] == '#1f77b4', cycle  # matplotlib default, unrestyled\n"
            "print('ok')\n"
        )],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_heatmap_falls_back_without_registered_house_cmap() -> None:
    """Without a registered dlab_div, the heatmap uses coolwarm."""
    if "dlab_div" in matplotlib.colormaps:
        matplotlib.colormaps.unregister("dlab_div")
    df = pd.DataFrame(np.random.default_rng(0).normal(size=(30, 3)),
                      columns=["a", "b", "c"])
    assert _heatmap_cmap_name(df) == "coolwarm"


def test_heatmap_prefers_registered_house_cmap() -> None:
    """With dlab_div registered, the heatmap uses it."""
    cmap = LinearSegmentedColormap.from_list(
        "dlab_div", ["#00513E", "#F7F7F7", "#974F44"]
    )
    matplotlib.colormaps.register(cmap, force=True)
    try:
        df = pd.DataFrame(np.random.default_rng(0).normal(size=(30, 3)),
                          columns=["a", "b", "c"])
        assert _heatmap_cmap_name(df) == "dlab_div"
    finally:
        matplotlib.colormaps.unregister("dlab_div")
