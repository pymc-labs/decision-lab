"""Tests for two-tier artifact discovery and the 'more files' expander (#48)."""

from pathlib import Path

import pytest

from dlab.tui.widgets.artifacts_pane import (
    ArtifactItem,
    ArtifactList,
    MoreFilesItem,
    discover_artifacts,
)


def _make_agent_dir(tmp_path: Path) -> Path:
    d = tmp_path / "agent"
    d.mkdir()
    # curated
    (d / "report.md").write_text("r")
    (d / "data.csv").write_text("a,b")
    (d / "plot.png").write_bytes(b"\x89PNG")
    # non-curated but real outputs (invisible before #48)
    (d / "analysis.json").write_text("{}")
    (d / "predictions.parquet").write_bytes(b"PAR1")
    (d / "report.html").write_text("<html>")
    (d / "diagram.svg").write_text("<svg>")
    # noise that must stay hidden even in expanded view
    (d / "module.pyc").write_bytes(b"\0")
    (d / "run.log").write_text("log")
    (d / ".hidden").write_text("x")
    return d


class TestDiscoverArtifacts:
    def test_default_view_is_curated_only(self, tmp_path: Path) -> None:
        d = _make_agent_dir(tmp_path)
        names = {p.name for p in discover_artifacts(tmp_path, d)}
        assert names == {"report.md", "data.csv", "plot.png"}

    def test_include_all_adds_real_outputs(self, tmp_path: Path) -> None:
        d = _make_agent_dir(tmp_path)
        names = {p.name for p in discover_artifacts(tmp_path, d, include_all=True)}
        assert {"analysis.json", "predictions.parquet", "report.html",
                "diagram.svg"} <= names

    def test_include_all_still_hides_noise(self, tmp_path: Path) -> None:
        d = _make_agent_dir(tmp_path)
        names = {p.name for p in discover_artifacts(tmp_path, d, include_all=True)}
        assert "module.pyc" not in names
        assert "run.log" not in names
        assert ".hidden" not in names


@pytest.mark.asyncio
class TestArtifactListExpander:
    """The list shows curated files + a MoreFilesItem that toggles the rest."""

    async def _mounted_list(self, tmp_path: Path):
        from textual.app import App

        d = _make_agent_dir(tmp_path)

        class _Host(App):
            def compose(self):
                yield ArtifactList(tmp_path, id="al")

        host = _Host()
        return host, d

    async def test_curated_shown_extra_hidden_by_default(self, tmp_path: Path) -> None:
        host, d = await self._mounted_list(tmp_path)
        async with host.run_test() as pilot:
            al = host.query_one("#al", ArtifactList)
            al._agent_dir = d
            al._agent_name = "worker"
            al._recompute()
            al._rebuild()
            await pilot.pause()
            items = list(al.query(ArtifactItem))
            more = list(al.query(MoreFilesItem))
            names = {i.file_path.name for i in items}
            assert names == {"report.md", "data.csv", "plot.png"}
            assert len(more) == 1  # the expander is present, collapsed

    async def test_expander_reveals_extra_files(self, tmp_path: Path) -> None:
        host, d = await self._mounted_list(tmp_path)
        async with host.run_test() as pilot:
            al = host.query_one("#al", ArtifactList)
            al._agent_dir = d
            al._agent_name = "worker"
            al._recompute()
            al._show_more = True
            al._rebuild()
            await pilot.pause()
            names = {i.file_path.name for i in al.query(ArtifactItem)}
            assert {"analysis.json", "predictions.parquet", "report.html"} <= names
