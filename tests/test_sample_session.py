"""
Integration tests against the committed golden session fixture
(tests/fixtures/sample_session/) — a small but structurally faithful
completed dlab run. These exercise the full read-side pipeline (parser →
session graph → timeline → viewer → connect TUI) against real files, catching
integration regressions that the per-module unit tests miss.

Regenerate the fixture with:
    python tests/fixtures/generate_sample_session.py
"""

import asyncio
import shutil
from pathlib import Path

import pytest

from dlab.opencode_logparser import build_session_graph, get_dlab_start_model, parse_log_file
from dlab.timeline import build_timeline
from dlab.tui.app import ConnectApp
from dlab.tui.widgets.artifacts_pane import ArtifactItem, discover_artifacts
from dlab.viewer.server import _collect_artifacts, export_viewer
from dlab.viewer.session_data import extract_process_tree

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session"


@pytest.fixture
def session(tmp_path: Path) -> Path:
    """A writable copy of the golden fixture (so tests never mutate it)."""
    dest = tmp_path / "session"
    shutil.copytree(FIXTURE, dest)
    return dest


def test_fixture_exists() -> None:
    assert (FIXTURE / "_opencode_logs" / "main.log").exists(), (
        "golden fixture missing — run tests/fixtures/generate_sample_session.py"
    )


class TestSessionGraph:
    def test_graph_shape(self, session: Path) -> None:
        root = build_session_graph(session / "_opencode_logs")
        assert root is not None
        assert root.name == "main"
        names = [c.name for c in root.children]
        assert names == ["instance-1", "instance-2", "consolidator"]

    def test_models_and_consolidator_flag(self, session: Path) -> None:
        root = build_session_graph(session / "_opencode_logs")
        assert root.model == "anthropic/claude-sonnet-4-5"
        cons = [c for c in root.children if c.is_consolidator]
        assert [c.name for c in cons] == ["consolidator"]

    def test_dlab_start_model_on_instances(self, session: Path) -> None:
        inst = parse_log_file(
            session / "_opencode_logs" / "poet-parallel-run-1700000000000" / "instance-1.log"
        )
        assert get_dlab_start_model(inst) == "anthropic/claude-sonnet-4-5"


class TestTimeline:
    def test_build_timeline_runs(self, session: Path) -> None:
        tl = build_timeline(session / "_opencode_logs")
        assert tl["total_events"] > 0
        sources = set(tl["file_summaries"])
        assert "main" in sources
        # instance + consolidator sources are present under the run prefix
        assert any("instance-1" in s for s in sources)


class TestViewer:
    def test_extract_and_collect_artifacts(self, session: Path) -> None:
        tree = extract_process_tree(session)
        artifacts = _collect_artifacts(session, tree)
        # Text artifact inlined as text; PNG as base64 data URI.
        assert any(
            k.endswith("final_poem.md") and v["type"] == "text" for k, v in artifacts.items()
        )
        assert any(
            k.endswith("plot.png") and v["type"] == "base64" for k, v in artifacts.items()
        )

    def test_export_produces_html(self, session: Path, tmp_path: Path) -> None:
        out = tmp_path / "viewer.html"
        rc = export_viewer(session, out)
        assert rc == 0
        html = out.read_text()
        assert "<html" in html.lower() or "<!doctype" in html.lower()
        assert out.stat().st_size > 1000


class TestArtifactDiscovery:
    def test_curated_default_lists_expected(self, session: Path) -> None:
        names = {p.name for p in discover_artifacts(session, session)}
        assert {"final_poem.md", "report.md", "data.csv", "plot.png"} <= names
        # non-curated types (json, parquet) are not in the curated default view
        assert "results.json" not in names
        assert "predictions.parquet" not in names

    def test_include_all_surfaces_extra(self, session: Path) -> None:
        # The "more files" expander (#48) reveals the non-curated outputs.
        names = {p.name for p in discover_artifacts(session, session, include_all=True)}
        assert "results.json" in names
        assert "predictions.parquet" in names


@pytest.mark.asyncio
async def test_connect_tui_boots_on_fixture(session: Path) -> None:
    app = ConnectApp(session)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.5)
        await pilot.pause()
        agents = app._state.agents
        assert "main" in agents
        assert len(agents) >= 3
    assert not (session / ".dlab_tui_crash.log").exists()
