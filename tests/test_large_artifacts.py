"""Tests for the large/binary artifact guards (issues #55, #48)."""

from pathlib import Path

from dlab.tui.widgets.artifacts_pane import (
    MAX_PREVIEW_BYTES,
    NonPreviewableDisplay,
    _looks_binary,
)
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


class TestNonPreviewableCard:
    """The TUI shows a metadata card instead of reading oversized or binary
    files (issues #55, #48)."""

    def test_too_large_card(self, tmp_path: Path) -> None:
        big = tmp_path / "predictions.parquet"
        big.write_bytes(b"\0" * (MAX_PREVIEW_BYTES + 10))
        rendered = NonPreviewableDisplay(big, "Too large to preview inline.").render().plain
        assert "predictions.parquet" in rendered
        assert "Too large" in rendered
        assert "MB" in rendered

    def test_binary_card(self, tmp_path: Path) -> None:
        f = tmp_path / "model.pkl"
        f.write_bytes(b"\x80\x04\x00binary")
        rendered = NonPreviewableDisplay(f, "Binary file — not previewable.").render().plain
        assert "model.pkl" in rendered
        assert "Binary" in rendered

    def test_show_file_gates_on_size_and_binary(self) -> None:
        # The preview path must check size AND binary before read_text.
        import inspect
        from dlab.tui.widgets import artifacts_pane

        src = inspect.getsource(artifacts_pane.FileViewer.show_file)
        assert src.index("MAX_PREVIEW_BYTES") < src.index("read_text")
        assert src.index("_looks_binary") < src.index("read_text")


class TestLooksBinary:
    def test_small_parquet_is_binary(self, tmp_path: Path) -> None:
        f = tmp_path / "x.parquet"
        f.write_bytes(b"PAR1\x00\x00\x01\x02\xff\xfe" + b"\x00" * 50)
        assert _looks_binary(f) is True

    def test_pickle_is_binary(self, tmp_path: Path) -> None:
        f = tmp_path / "x.pkl"
        f.write_bytes(b"\x80\x04\x95\x00\x00")
        assert _looks_binary(f) is True

    def test_text_types_are_not_binary(self, tmp_path: Path) -> None:
        for name, content in (
            ("a.json", '{"k": "v"}'),
            ("a.csv", "col1,col2\n1,2\n"),
            ("a.svg", "<svg></svg>"),
            ("a.txt", "hello wörld"),  # non-ASCII but valid UTF-8
        ):
            f = tmp_path / name
            f.write_text(content, encoding="utf-8")
            assert _looks_binary(f) is False, name

    def test_reads_only_a_bounded_prefix(self, tmp_path: Path) -> None:
        # A NUL only past the 8 KB window is not scanned -> treated as text.
        f = tmp_path / "big.txt"
        f.write_bytes(b"a" * 8192 + b"\x00")
        assert _looks_binary(f) is False
