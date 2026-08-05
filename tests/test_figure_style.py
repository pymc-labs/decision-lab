"""
Tests for the decision-lab house figure style (dlab/figure_style.py and the
vendored assets in dlab/data/figure_style/).
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import matplotlib
import yaml

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  — backend must be set first

import dlab.data.figure_style  # noqa: E402
from dlab.config import load_dpack_config  # noqa: E402
from dlab.docker import build_runner_script  # noqa: E402
from dlab.figure_style import (  # noqa: E402
    FIGURE_STYLE_SKILL_NAME,
    STYLE_DIR_NAME,
    figure_style_enabled,
    figure_style_shell_exports,
    install_figure_style,
)
from dlab.session import (  # noqa: E402
    INSTANCE_ENV_EXACT,
    create_session,
    write_instance_env_allowlist,
)


ASSET_DIR: Path = Path(dlab.data.figure_style.__file__).parent

# Must match the cycle in matplotlibrc and PALETTE in dlab_plotstyle.py
EXPECTED_CYCLE: list[str] = [
    "#007d5f", "#e87a69", "#50b1dc", "#136a94",
    "#4e9a5b", "#ccae59", "#7d4778", "#808f3b",
]


def _load_plotstyle_module() -> ModuleType:
    """Import the vendored dlab_plotstyle.py the way an agent script would."""
    spec = importlib.util.spec_from_file_location(
        "dlab_plotstyle", ASSET_DIR / "dlab_plotstyle.py"
    )
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestConfigSwitch:
    def test_figure_style_default_on(self, dpack_config_dir: Path) -> None:
        """figure_style defaults to True when absent from config.yaml."""
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        assert config["use_dlab_plot_style"] is True
        assert figure_style_enabled(config) is True

    def test_figure_style_opt_out(self, dpack_config_dir: Path) -> None:
        """use_dlab_plot_style: false in config.yaml disables the style."""
        config_path: Path = dpack_config_dir / "config.yaml"
        raw: dict[str, Any] = yaml.safe_load(config_path.read_text())
        raw["use_dlab_plot_style"] = False
        config_path.write_text(yaml.dump(raw))

        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        assert config["use_dlab_plot_style"] is False
        assert figure_style_enabled(config) is False


class TestSessionInstall:
    def test_create_session_installs_style(
        self, dpack_config_dir: Path, work_dir: Path
    ) -> None:
        """A new session gets _style/ assets and the figure-style skill."""
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        create_session(config, None, work_dir=str(work_dir))

        style_dir: Path = work_dir / STYLE_DIR_NAME
        assert (style_dir / "matplotlibrc").exists()
        assert (style_dir / "dlab_plotstyle.py").exists()

        skill_md: Path = (
            work_dir / ".opencode" / "skills" / FIGURE_STYLE_SKILL_NAME / "SKILL.md"
        )
        assert skill_md.exists()
        assert f"name: {FIGURE_STYLE_SKILL_NAME}" in skill_md.read_text()

    def test_create_session_opt_out_skips_style(
        self, dpack_config_dir: Path, work_dir: Path
    ) -> None:
        """use_dlab_plot_style: false leaves the work dir free of style assets."""
        config_path: Path = dpack_config_dir / "config.yaml"
        raw: dict[str, Any] = yaml.safe_load(config_path.read_text())
        raw["use_dlab_plot_style"] = False
        config_path.write_text(yaml.dump(raw))

        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        create_session(config, None, work_dir=str(work_dir))

        assert not (work_dir / STYLE_DIR_NAME).exists()
        assert not (
            work_dir / ".opencode" / "skills" / FIGURE_STYLE_SKILL_NAME
        ).exists()

    def test_install_figure_style_direct(self, tmp_path: Path) -> None:
        """install_figure_style writes assets identical to package data."""
        (tmp_path / ".opencode").mkdir()
        install_figure_style(str(tmp_path))

        written: str = (tmp_path / STYLE_DIR_NAME / "matplotlibrc").read_text()
        assert written == (ASSET_DIR / "matplotlibrc").read_text()


class TestMatplotlibrc:
    def test_rc_is_valid_and_on_palette(self) -> None:
        """The rc parses without errors and carries the validated cycle."""
        rc = matplotlib.rc_params_from_file(
            ASSET_DIR / "matplotlibrc",
            fail_on_error=True,
            use_default_template=False,
        )
        cycle_colors: list[str] = [
            matplotlib.colors.to_hex(f"#{c}" if not c.startswith("#") else c)
            for c in rc["axes.prop_cycle"].by_key()["color"]
        ]
        assert cycle_colors == EXPECTED_CYCLE
        assert rc["axes.spines.top"] is False
        assert rc["axes.spines.right"] is False
        assert rc["legend.frameon"] is False
        assert "Inter" in rc["font.sans-serif"]

    def test_rc_avoids_pymc_labs_brand_colors(self) -> None:
        """The palette must not reuse the PyMC Labs brand colors."""
        pymc_brand: set[str] = {"#0c1f40", "#9faae2", "#b4e7dd", "#f6ae72"}
        assert pymc_brand.isdisjoint(set(EXPECTED_CYCLE))


class TestPlotstyleModule:
    def test_palette_matches_rc_cycle(self) -> None:
        """PALETTE values and order mirror the rc color cycle."""
        module: ModuleType = _load_plotstyle_module()
        assert [c.lower() for c in module.PALETTE.values()] == EXPECTED_CYCLE
        assert set(module.PALETTE_LIGHT) == set(module.PALETTE)
        assert set(module.PALETTE_DARK) == set(module.PALETTE)

    def test_fill_between_defaults_to_no_edge(self) -> None:
        """Importing the module makes fill_between bands edge-free."""
        module: ModuleType = _load_plotstyle_module()
        fig, ax = plt.subplots()
        try:
            band = ax.fill_between(
                [0.0, 1.0], [0.0, 0.0], [1.0, 1.0],
                color=module.PALETTE["pine"],
            )
            assert band.get_edgecolor().size == 0  # 'none' -> empty array
            # Explicit edge kwargs are dropped too — bands never carry an
            # outline (libraries like arviz outline their HDI bands)
            band2 = ax.fill_between(
                [0.0, 1.0], [0.0, 0.0], [1.0, 1.0],
                edgecolor="black", linewidth=2.0,
            )
            assert band2.get_edgecolor().size == 0
        finally:
            plt.close(fig)

    def test_house_colormaps_registered(self) -> None:
        """dlab_div and dlab_seq are registered; dlab_seq is the default."""
        module: ModuleType = _load_plotstyle_module()
        assert module is not None
        assert "dlab_div" in matplotlib.colormaps
        assert "dlab_seq" in matplotlib.colormaps
        assert matplotlib.rcParams["image.cmap"] == "dlab_seq"

    def test_legend_frameon_is_stripped(self) -> None:
        """frameon=True is dropped: legends stay frameless (rc applies)."""
        module: ModuleType = _load_plotstyle_module()
        assert module is not None
        fig, ax = plt.subplots()
        try:
            ax.plot([0.0, 1.0], [0.0, 1.0], label="a")
            legend = ax.legend(frameon=True)
            assert legend.get_frame_on() is False
        finally:
            plt.close(fig)

    def test_text_bbox_is_stripped(self) -> None:
        """bbox boxes around text/annotations are dropped."""
        module: ModuleType = _load_plotstyle_module()
        assert module is not None
        fig, ax = plt.subplots()
        try:
            txt = ax.text(0.5, 0.5, "r = 0.5", bbox=dict(boxstyle="round"))
            ann = ax.annotate("note", xy=(0.2, 0.2), bbox=dict(boxstyle="round"))
            assert txt.get_bbox_patch() is None
            assert ann.get_bbox_patch() is None
        finally:
            plt.close(fig)

    def test_suptitle_defaults_to_title_ink(self) -> None:
        """suptitle color defaults to TITLE_INK (explicit color still wins)."""
        module: ModuleType = _load_plotstyle_module()
        fig = plt.figure()
        try:
            text = fig.suptitle("proof")
            assert text.get_color() == module.TITLE_INK
        finally:
            plt.close(fig)

    def test_axis_end_tick_caps(self) -> None:
        """add_axis_end_tick_caps returns cap artists on a fitted axis."""
        module: ModuleType = _load_plotstyle_module()
        fig, ax = plt.subplots()
        try:
            ax.plot([0.0, 1.0, 2.0], [1.0, 3.0, 2.0])
            ax.set_xlim(0.0, 1.7)
            caps = module.add_axis_end_tick_caps(ax)
            assert len(caps) == 2
            fig.canvas.draw()
        finally:
            plt.close(fig)


class TestEnvActivation:
    def test_shell_exports(self) -> None:
        """Exports point at _style and prepend (not clobber) PYTHONPATH."""
        exports: str = figure_style_shell_exports("/workspace")
        assert 'export MATPLOTLIBRC="/workspace/_style/matplotlibrc"' in exports
        assert 'export PYTHONPATH="/workspace/_style${PYTHONPATH:+:$PYTHONPATH}"' in exports

    def test_runner_script_includes_prelude(self) -> None:
        """The docker runner script carries the exports before opencode runs."""
        prelude: str = figure_style_shell_exports("/workspace")
        script: str = build_runner_script("/.prompt.txt", "anthropic/x", "main", prelude)
        assert script.index("MATPLOTLIBRC") < script.index("opencode run")

    def test_instance_env_allowlist_forwards_matplotlibrc(
        self, tmp_path: Path
    ) -> None:
        """Parallel instances inherit MATPLOTLIBRC through the allowlist."""
        assert "MATPLOTLIBRC" in INSTANCE_ENV_EXACT

        write_instance_env_allowlist(tmp_path)
        allowlist: dict[str, Any] = json.loads(
            (tmp_path / "instance-env-allowlist.json").read_text()
        )
        assert "MATPLOTLIBRC" in allowlist["exact"]
        assert "PYTHONPATH" in allowlist["exact"]
