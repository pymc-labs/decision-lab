"""
decision-lab house figure style: session-level matplotlib styling.

Enforcement is layered so the style survives even when the agent never thinks
about it:

1. ``_style/matplotlibrc`` — activated through the MATPLOTLIBRC environment
   variable exported by the session runner script; styles every matplotlib
   figure with zero cooperation from the agent.
2. ``_style/dlab_plotstyle.py`` — importable because ``_style`` is prepended
   to PYTHONPATH; exposes the palette by name, defaults ``fill_between``
   edges to ``none``, and provides an axis end-cap helper. Forgetting the
   import degrades gracefully (cosmetic loss only).
3. ``.opencode/skills/dlab-figure-style`` — the judgment rules the rc cannot
   enforce (never call ``sns.set_theme``/``plt.style.use``, the scatter
   edgecolor trap, z-order, legends).

The environment variables propagate to parallel agent instances through the
instance env allowlist in ``session.py``. decision-packs opt out with
``use_dlab_plot_style: false`` in config.yaml.
"""

from importlib.resources import files
from pathlib import Path
from typing import Any


FIGURE_STYLE_SKILL_NAME: str = "dlab-figure-style"
STYLE_DIR_NAME: str = "_style"


def _read_asset(name: str) -> str:
    """Read a vendored figure-style asset from package data."""
    return files("dlab.data.figure_style").joinpath(name).read_text()


def figure_style_enabled(config: dict[str, Any]) -> bool:
    """
    Whether the decision-pack uses the decision-lab figure style.

    Parameters
    ----------
    config : dict[str, Any]
        decision-pack configuration. The ``use_dlab_plot_style`` key defaults to
        True; packs opt out with ``use_dlab_plot_style: false``.

    Returns
    -------
    bool
        True if the figure style should be installed and activated.
    """
    return bool(config.get("use_dlab_plot_style", True))


def install_figure_style(work_dir: str) -> None:
    """
    Write the figure-style assets into a session work directory.

    Creates ``_style/matplotlibrc`` and ``_style/dlab_plotstyle.py`` in the
    work dir, and the ``dlab-figure-style`` skill under ``.opencode/skills/``.

    Parameters
    ----------
    work_dir : str
        Path to the session work directory (must contain ``.opencode/``).
    """
    work_path: Path = Path(work_dir)

    style_dir: Path = work_path / STYLE_DIR_NAME
    style_dir.mkdir(exist_ok=True)
    (style_dir / "matplotlibrc").write_text(_read_asset("matplotlibrc"))
    (style_dir / "dlab_plotstyle.py").write_text(_read_asset("dlab_plotstyle.py"))

    skill_dir: Path = work_path / ".opencode" / "skills" / FIGURE_STYLE_SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_read_asset("SKILL.md"))


def figure_style_shell_exports(workspace_root: str) -> str:
    """
    Shell export lines that activate the figure style for a session.

    MATPLOTLIBRC points matplotlib at the injected rc; ``_style`` is
    *prepended* to PYTHONPATH (preserving any value set by the image or env
    file) so ``import dlab_plotstyle`` works from any directory. These lines
    are inserted into the opencode runner script; the spawned opencode
    process inherits them and forwards both variables to parallel instances
    via the instance env allowlist.

    Parameters
    ----------
    workspace_root : str
        Absolute path of the work directory as seen by the session
        (``/workspace`` in Docker mode, the host work dir in local mode).

    Returns
    -------
    str
        Newline-terminated ``export`` lines for the bash runner script.
    """
    style_dir: str = f"{workspace_root.rstrip('/')}/{STYLE_DIR_NAME}"
    return (
        f'export MATPLOTLIBRC="{style_dir}/matplotlibrc"\n'
        f'export PYTHONPATH="{style_dir}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
    )
