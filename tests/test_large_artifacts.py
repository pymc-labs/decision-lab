"""Tests for the large-artifact memory guards (issue #55)."""

from pathlib import Path

from dlab.tui.widgets.artifacts_pane import MAX_PREVIEW_BYTES, LargeFileDisplay
from dlab.viewer.server import MAX_INLINE_BYTES, _collect_artifacts


class TestCollectArtifactsSizeGuard:
    """_collect_artifacts must not read oversized files into the session JSON."""

    def _session(self, *paths: str) -> dict:
        return {"tree": {"artifacts": [{"path": p} for p in paths]}}

    def test_large_binary_not_inlined(self, tmp_path: Path) -> None:
        big = tmp_path / "predictions.parquet"
        big.write_bytes(b"\0" * (MAX_INLINE_BYTES + 1))
        amap = _collect_artifacts(tmp_path, self._session("predictions.parquet"))
        entry = amap["predictions.parquet"]
        assert entry["type"] == "too_large"
        assert entry["size"] > MAX_INLINE_BYTES
        # Crucially, the file content was NOT read/encoded into the JSON.
        assert "content" not in entry

    def test_large_text_not_inlined(self, tmp_path: Path) -> None:
        big = tmp_path / "huge.csv"
        big.write_bytes(b"a,b\n" + b"1,2\n" * (MAX_INLINE_BYTES // 4))
        amap = _collect_artifacts(tmp_path, self._session("huge.csv"))
        assert amap["huge.csv"]["type"] == "too_large"
        assert "content" not in amap["huge.csv"]

    def test_small_file_still_inlined(self, tmp_path: Path) -> None:
        small = tmp_path / "summary.txt"
        small.write_text("all good")
        amap = _collect_artifacts(tmp_path, self._session("summary.txt"))
        assert amap["summary.txt"]["type"] == "text"
        assert amap["summary.txt"]["content"] == "all good"

    def test_small_binary_still_base64(self, tmp_path: Path) -> None:
        img = tmp_path / "plot.png"
        img.write_bytes(b"\x89PNG\r\n" + b"\0" * 100)
        amap = _collect_artifacts(tmp_path, self._session("plot.png"))
        assert amap["plot.png"]["type"] == "base64"
        assert amap["plot.png"]["content"].startswith("data:")


class TestLargeFileDisplay:
    """The TUI shows a metadata card instead of reading an oversized file."""

    def test_card_renders_without_reading_content(self, tmp_path: Path) -> None:
        big = tmp_path / "predictions.parquet"
        big.write_bytes(b"\0" * (MAX_PREVIEW_BYTES + 10))
        card = LargeFileDisplay(big)
        rendered = card.render().plain
        assert "predictions.parquet" in rendered
        assert "Too large" in rendered
        assert "MB" in rendered

    def test_show_file_gates_on_size(self) -> None:
        # The preview path must check the size cap before read_text (#55).
        import inspect
        from dlab.tui.widgets import artifacts_pane

        src = inspect.getsource(artifacts_pane.FileViewer.show_file)
        assert "MAX_PREVIEW_BYTES" in src
        assert src.index("MAX_PREVIEW_BYTES") < src.index("read_text")
