"""
Artifact widgets for browsing and viewing agent output files.

Provides:
- ArtifactList: File list in left sidebar
- FileViewer: Scrollable file content viewer with image support
"""

import csv
import io
import os
import re
import subprocess
import sys
from pathlib import Path

from rich.console import Group
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import DataTable, ListItem, ListView, Static

# Curated default view — the artifact types worth surfacing prominently.
ARTIFACT_EXTENSIONS = {".md", ".py", ".txt", ".csv", ".png", ".jpg", ".jpeg", ".pdf"}

# The list shows the curated types by default and, behind a "N more files"
# expander, everything else under the agent dir EXCEPT these clearly-irrelevant
# extensions (and dotfiles). This surfaces .json/.parquet/.html/... outputs
# without whitelist catch-up or cluttering the default view (issue #48).
HIDDEN_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".so", ".o", ".a", ".class",
    ".lock", ".tmp", ".temp", ".swp", ".swo", ".bak",
    ".log", ".pid", ".cache",
}

# Files larger than this are not read into memory for preview (issue #55);
# a metadata card with an "open externally" hint is shown instead.
MAX_PREVIEW_BYTES = 5 * 1024 * 1024

# Directories to exclude from artifact discovery
EXCLUDE_DIRS = {
    ".git",
    ".opencode",
    "_opencode_logs",
    "_docker",
    "_hooks",
    "node_modules",
    "__pycache__",
    "data",
    ".venv",
    "venv",
    ".env",
    "env",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
}


def open_file_externally(path: Path | None) -> bool:
    """
    Open a file with the system's default application, without a shell.

    Artifact filenames are agent-controlled, so they must never pass
    through a shell: on Windows this uses ``os.startfile`` (no cmd.exe),
    on macOS/Linux the platform opener binary with an argument list.

    Parameters
    ----------
    path : Path | None
        File to open.

    Returns
    -------
    bool
        True if an opener was launched, False if the path is missing/does
        not exist or no opener is available on this system.
    """
    if not path or not path.exists():
        return False
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        # Opener binary missing (e.g. no xdg-open) or file vanished —
        # report failure instead of crashing the TUI.
        return False
    return True

# Image extensions
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def get_agent_directory(work_dir: Path, agent_name: str | None) -> Path | None:
    """
    Map agent display name to its artifact directory.

    Agent names from logs use pattern: poet-parallel-run-TIMESTAMP/instance-N
    But actual work files are in: parallel/run-TIMESTAMP/instance-N/

    Parameters
    ----------
    work_dir : Path
        Work directory path.
    agent_name : str | None
        Agent display name (may be shortened).

    Returns
    -------
    Path | None
        Directory containing agent's artifacts, or None for root.
    """
    if not agent_name:
        return None

    # Main agent: use root directory
    if agent_name.startswith("main"):
        return None

    # Shortened parallel agent name: ⟝ poet …28/ inst-1
    match = re.match(r"^⟝ (.+) …(\d+)/ (.+)$", agent_name)
    if match:
        number_suffix = match.group(2)
        instance_part = match.group(3)

        # Expand instance abbreviations
        if instance_part.startswith("inst-"):
            instance_part = "instance-" + instance_part[5:]
        elif instance_part == "cnsldtr":
            instance_part = "consolidator"
        elif instance_part.startswith("cnsldtr-"):
            instance_part = "consolidator-" + instance_part[8:]

        # Find matching run directory in parallel/
        parallel_dir = work_dir / "parallel"
        if parallel_dir.exists():
            for run_dir in parallel_dir.iterdir():
                if run_dir.is_dir() and run_dir.name.endswith(number_suffix):
                    return run_dir / instance_part

    # Full parallel agent name: poet-parallel-run-TIMESTAMP/instance-N
    # Maps to: parallel/run-TIMESTAMP/instance-N
    full_match = re.match(r"^.+-parallel-run-(\d+)/(.+)$", agent_name)
    if full_match:
        timestamp = full_match.group(1)
        instance_part = full_match.group(2)
        return work_dir / "parallel" / f"run-{timestamp}" / instance_part

    return None


def is_parallel_run_dir(name: str) -> bool:
    """Check if directory name matches parallel run pattern."""
    # Matches both 'parallel' dir and 'run-TIMESTAMP' subdirs
    return name == "parallel" or name.startswith("run-")


def _looks_binary(path: Path) -> bool:
    """
    Heuristically decide whether a file is binary, reading only a bounded
    prefix (never the whole file).

    A file is treated as binary if the first 8 KB contains a NUL byte or is
    not valid UTF-8. Used to show a metadata card instead of previewing
    non-text files as garbled text (issue #48).
    """
    try:
        with open(path, "rb") as f:
            chunk: bytes = f.read(8192)
    except OSError:
        return False
    if b"\x00" in chunk:
        return True
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        # A multibyte char split at the 8 KB boundary would also raise; that
        # is rare and only misclassifies a borderline text file as binary,
        # which merely shows a card — acceptable.
        return True
    return False


def discover_artifacts(
    work_dir: Path,
    agent_dir: Path | None,
    is_main: bool = False,
    include_all: bool = False,
) -> list[Path]:
    """
    Discover artifact files for an agent.

    Parameters
    ----------
    work_dir : Path
        Work directory path.
    agent_dir : Path | None
        Agent-specific directory, or None for root.
    is_main : bool
        Whether this is the main agent. If True, excludes parallel run dirs.

    Returns
    -------
    list[Path]
        List of artifact paths relative to work_dir.
    """
    search_dir = agent_dir if agent_dir else work_dir
    if not search_dir.exists():
        return []

    artifacts: list[Path] = []
    base = agent_dir if agent_dir else work_dir

    for root, dirs, files in os.walk(search_dir, topdown=True):
        root_path = Path(root)

        # Prune excluded and parallel-run directories in-place so os.walk
        # never descends into them — O(relevant files only).
        dirs[:] = [
            d
            for d in dirs
            if d not in EXCLUDE_DIRS and not (is_main and is_parallel_run_dir(d))
        ]

        for filename in files:
            file_path = root_path / filename
            suffix = file_path.suffix.lower()
            if include_all:
                # Everything except dotfiles and clearly-irrelevant extensions.
                if filename.startswith(".") or suffix in HIDDEN_EXTENSIONS:
                    continue
            else:
                # Curated default view.
                if suffix not in ARTIFACT_EXTENSIONS:
                    continue
            try:
                artifacts.append(file_path.relative_to(base))
            except ValueError:
                artifacts.append(file_path)

    return sorted(artifacts)


def get_file_icon(path: Path) -> str:
    """Get short text label for file type."""
    suffix = path.suffix.lower()
    labels: dict[str, str] = {
        ".md": "md",
        ".py": "py",
        ".txt": "tx",
        ".csv": "csv",
        ".png": "img",
        ".jpg": "img",
        ".jpeg": "img",
        ".pdf": "pdf",
    }
    return labels.get(suffix, "  ")


class ArtifactItem(ListItem):
    """List item for a single artifact file."""

    def __init__(self, path: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.file_path = path

    def compose(self):
        """Compose the widget."""
        tag: str = get_file_icon(self.file_path)
        if self.file_path.parent != Path("."):
            parent = str(self.file_path.parent)
            if len(parent) > 10:
                parent = f"{parent[:5]}…{parent[-5:]}"
            display_path = f"{parent}/{self.file_path.name}"
        else:
            display_path = self.file_path.name

        max_len: int = 19
        if len(display_path) > max_len:
            display_path = display_path[: max_len - 1] + "…"

        text = Text()
        text.append(f"{tag:>3}", style="dim")
        text.append(f" {display_path}")
        yield Static(text)


_ARTIFACT_TYPE_ORDER: dict[str, int] = {
    ".md": 0,
    ".py": 1,
    ".png": 2,
    ".jpg": 2,
    ".jpeg": 2,
    ".csv": 3,
}


def _sort_artifacts(artifacts: list[Path]) -> list[Path]:
    """Sort artifacts by type (md, py, img, csv, rest) then name."""
    return sorted(
        artifacts,
        key=lambda p: (_ARTIFACT_TYPE_ORDER.get(p.suffix.lower(), 99), p.name.lower()),
    )


class MoreFilesItem(ListItem):
    """Expander row that reveals/hides the non-curated files (issue #48)."""

    def __init__(self, count: int, expanded: bool, **kwargs) -> None:
        super().__init__(**kwargs)
        self._count = count
        self._expanded = expanded

    def compose(self):
        arrow: str = "▾" if self._expanded else "▸"
        if self._expanded:
            label: str = "fewer files"
        else:
            plural: str = "s" if self._count != 1 else ""
            label = f"{self._count} more file{plural}"
        yield Static(Text(f"{arrow} {label}", style="dim italic"))


class ArtifactList(ListView):
    """
    File list in left sidebar.

    Shows the curated artifact types for the selected agent, plus an
    expandable "N more files" row revealing everything else the agent wrote.
    """

    class FileSelected(Message):
        """Message sent when a file is selected."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    def __init__(self, work_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._work_dir = work_dir
        self._agent_dir: Path | None = None
        self._artifacts: list[Path] = []       # curated
        self._extra: list[Path] = []           # non-curated ("more files")
        self._agent_name: str | None = None
        self._show_more: bool = False

    def _recompute(self) -> None:
        """Split the agent's files into curated and extra lists."""
        is_main = self._agent_name is not None and self._agent_name.startswith("main")
        all_files = discover_artifacts(
            self._work_dir, self._agent_dir, is_main=is_main, include_all=True
        )
        curated = [p for p in all_files if p.suffix.lower() in ARTIFACT_EXTENSIONS]
        extra = [p for p in all_files if p.suffix.lower() not in ARTIFACT_EXTENSIONS]
        self._artifacts = _sort_artifacts(curated)
        self._extra = _sort_artifacts(extra)

    def _rebuild(self) -> None:
        """Repopulate the list from the current curated/extra state."""
        self.clear()
        if not self._artifacts and not self._extra:
            self.append(ListItem(Static(Text("No files", style="dim italic"))))
            return
        for path in self._artifacts:
            self.append(ArtifactItem(path))
        if self._extra:
            self.append(MoreFilesItem(len(self._extra), self._show_more))
            if self._show_more:
                for path in self._extra:
                    self.append(ArtifactItem(path))

    def set_agent(self, agent_name: str | None) -> None:
        """Update artifacts for selected agent."""
        self._agent_name = agent_name
        self._agent_dir = get_agent_directory(self._work_dir, agent_name)
        self._show_more = False  # collapse when switching agents
        self._recompute()
        self._rebuild()

    def refresh_if_changed(self) -> None:
        """Re-discover artifacts and update list only if files changed."""
        if self._agent_name is None:
            return

        self._agent_dir = get_agent_directory(self._work_dir, self._agent_name)
        old_artifacts, old_extra = self._artifacts, self._extra
        self._recompute()
        if self._artifacts != old_artifacts or self._extra != old_extra:
            self._rebuild()

    def _resolve_path(self, rel_path: Path) -> Path:
        """Resolve a relative artifact path to an absolute path."""
        base = self._agent_dir if self._agent_dir else self._work_dir
        return base / rel_path

    def on_focus(self) -> None:
        """Auto-highlight first item when focused."""
        if self.index is None and self.children:
            self.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle selection (Enter key)."""
        if isinstance(event.item, MoreFilesItem):
            self._show_more = not self._show_more
            self._rebuild()
            return
        if isinstance(event.item, ArtifactItem):
            self.post_message(
                self.FileSelected(self._resolve_path(event.item.file_path))
            )

    def get_highlighted_path(self) -> Path | None:
        """Get the path of the currently highlighted file."""
        if self.highlighted_child is not None:
            if isinstance(self.highlighted_child, ArtifactItem):
                return self._resolve_path(self.highlighted_child.file_path)
        return None

    def open_highlighted(self) -> bool:
        """
        Open the highlighted file in the system's default viewer.

        Returns
        -------
        bool
            True if file was opened, False if no file highlighted.
        """
        return open_file_externally(self.get_highlighted_path())


class FileViewer(VerticalScroll, can_focus=True):
    """
    Scrollable file content viewer with image support.

    Displays:
    - Markdown files: rendered as markdown
    - Python files: syntax highlighted
    - Images: inline rendering (iTerm2) or info display
    - Other files: plain text
    """

    DEFAULT_CSS = """
    FileViewer {
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("up", "scroll_up", "Up"),
        ("down", "scroll_down", "Down"),
        ("pageup", "page_up", "Page Up"),
        ("pagedown", "page_down", "Page Down"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._file_path: Path | None = None

    def show_file(self, path: Path) -> None:
        """Display file content."""
        self._file_path = path

        # Clear existing content
        self.remove_children()

        if not path.exists():
            self.mount(Static(Text(f"File not found: {path}", style="red")))
            return

        suffix = path.suffix.lower()

        # Image files
        if suffix in IMAGE_EXTENSIONS:
            self.mount(ImageDisplay(path))
            return

        # PDF files
        if suffix == ".pdf":
            self.mount(PdfDisplay(path))
            return

        # Too large to preview safely — show a metadata card instead of
        # reading the whole file into memory (issue #55).
        try:
            if path.stat().st_size > MAX_PREVIEW_BYTES:
                self.mount(NonPreviewableDisplay(path, "Too large to preview inline."))
                return
        except OSError:
            pass

        # Binary (parquet, nc, pkl, ...) — a metadata card, not garbled text
        # (issue #48). Images and PDFs were already handled above.
        if _looks_binary(path):
            self.mount(NonPreviewableDisplay(path, "Binary file — not previewable."))
            return

        # Read text content
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            self.mount(Static(Text(f"Error reading file: {e}", style="red")))
            return

        # Markdown files
        if suffix == ".md":
            self.mount(MarkdownDisplay(content))
            return

        # Python files
        if suffix == ".py":
            self.mount(CodeDisplay(content, "python"))
            return

        # CSV files
        if suffix == ".csv":
            self.mount(CsvDisplay(content))
            return

        # Default: plain text
        self.mount(Static(Text(content)))

    def show_placeholder(self) -> None:
        """Show placeholder when no file selected."""
        self.remove_children()
        self.mount(Static(Text("Select a file to preview", style="dim italic")))

    def action_scroll_up(self) -> None:
        """Scroll up."""
        self.scroll_up()

    def action_scroll_down(self) -> None:
        """Scroll down."""
        self.scroll_down()

    def action_page_up(self) -> None:
        """Page up."""
        self.scroll_page_up()

    def action_page_down(self) -> None:
        """Page down."""
        self.scroll_page_down()

    def get_current_file(self) -> Path | None:
        """Get the currently displayed file path."""
        return self._file_path

    def open_external(self) -> bool:
        """
        Open the current file in the system's default viewer.

        Returns
        -------
        bool
            True if file was opened, False if no file selected.
        """
        return open_file_externally(self._file_path)


class ImageDisplay(Static):
    """Display image info with clickable path to open externally.

    Note: iTerm2 inline images don't work inside Textual TUIs because
    Textual uses its own virtual screen buffer that doesn't pass through
    terminal escape sequences.
    """

    def __init__(self, path: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._path = path

    def render(self) -> Text:
        """Render image info with clickable path."""
        if not self._path.exists():
            return Text(f"Image not found: {self._path}", style="red")

        size = self._path.stat().st_size
        size_str = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} bytes"

        # Try to get image dimensions
        dimensions = ""
        try:
            from PIL import Image

            with Image.open(self._path) as img:
                dimensions = f"{img.width} x {img.height} px"
        except ImportError:
            pass
        except Exception:
            pass

        text = Text()
        text.append(f"{self._path.name}\n\n", style="bold")
        text.append("Path: ", style="")
        text.append(f"{self._path}", style="underline cyan")
        text.append("\n", style="")
        text.append(f"Size: {size_str}\n", style="dim")
        if dimensions:
            text.append(f"Dimensions: {dimensions}\n", style="dim")
        text.append("\n")
        text.append("Click path or press ", style="dim")
        text.append("o", style="bold cyan")
        text.append(" to open", style="dim")

        return text

    def on_click(self) -> None:
        """Handle click - open the file externally."""
        self._open_file()

    def _open_file(self) -> None:
        """Open the file in system default viewer."""
        open_file_externally(self._path)


class PdfDisplay(Static):
    """Display PDF info with clickable path to open externally."""

    def __init__(self, path: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._path = path

    def render(self) -> Text:
        """Render PDF info with clickable path."""
        if not self._path.exists():
            return Text(f"PDF not found: {self._path}", style="red")

        size = self._path.stat().st_size
        size_str = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} bytes"

        text = Text()
        text.append(f"{self._path.name}\n\n", style="bold")
        text.append("Path: ", style="")
        text.append(f"{self._path}", style="underline cyan")
        text.append("\n", style="")
        text.append(f"Size: {size_str}\n", style="dim")
        text.append("\n")
        text.append("Click path or press ", style="dim")
        text.append("o", style="bold cyan")
        text.append(" to open", style="dim")

        return text

    def on_click(self) -> None:
        """Handle click - open the file externally."""
        self._open_file()

    def _open_file(self) -> None:
        """Open the file in system default viewer."""
        open_file_externally(self._path)


class NonPreviewableDisplay(Static):
    """Metadata card for a file that is not previewed inline — because it is
    too large (issue #55) or binary (issue #48). Shows name/size and an
    open-externally hint instead of dumping bytes into the viewer."""

    def __init__(self, path: Path, reason: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._path = path
        self._reason = reason

    def render(self) -> Text:
        if not self._path.exists():
            return Text(f"File not found: {self._path}", style="red")

        size: int = self._path.stat().st_size
        size_str: str = (
            f"{size / (1024 * 1024):.1f} MB"
            if size >= 1024 * 1024
            else f"{size / 1024:.1f} KB"
        )

        text = Text()
        text.append(f"{self._path.name}\n\n", style="bold")
        text.append(f"Size: {size_str}\n", style="dim")
        text.append(f"{self._reason}\n\n", style="yellow")
        text.append("Path: ", style="")
        text.append(f"{self._path}", style="underline cyan")
        text.append("\n\n")
        text.append("Click path or press ", style="dim")
        text.append("o", style="bold cyan")
        text.append(" to open externally", style="dim")
        return text

    def on_click(self) -> None:
        """Handle click - open the file externally."""
        open_file_externally(self._path)


class MarkdownDisplay(Static):
    """Display markdown content rendered."""

    def __init__(self, content: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._content = content

    def render(self):
        """Render markdown."""
        return Markdown(self._content)


class CodeDisplay(Static):
    """Display code with syntax highlighting."""

    def __init__(self, content: str, language: str = "python", **kwargs) -> None:
        super().__init__(**kwargs)
        self._content = content
        self._language = language

    def render(self):
        """Render code with syntax highlighting."""
        return Syntax(
            self._content,
            self._language,
            theme="monokai",
            line_numbers=True,
        )


class CsvDisplay(DataTable):
    """Display CSV content as a data table."""

    DEFAULT_CSS = """
    CsvDisplay {
        height: auto;
        max-height: 100%;
    }
    """

    def __init__(self, content: str, max_rows: int = 500, **kwargs) -> None:
        super().__init__(**kwargs)
        self._content = content
        self._max_rows = max_rows

    def on_mount(self) -> None:
        """Parse CSV and populate table on mount."""
        try:
            reader = csv.reader(io.StringIO(self._content))
            rows = list(reader)

            if not rows:
                return

            # First row as headers
            headers = rows[0]
            for col_idx, header in enumerate(headers):
                self.add_column(header or f"col_{col_idx}", key=str(col_idx))

            # Add data rows (limit to max_rows)
            for row in rows[1 : self._max_rows + 1]:
                # Pad row if needed
                while len(row) < len(headers):
                    row.append("")
                self.add_row(*row[: len(headers)])

            # Show truncation message if needed
            if len(rows) > self._max_rows + 1:
                truncated = len(rows) - self._max_rows - 1
                self.add_row(
                    *[
                        f"... {truncated} more rows ..." if i == 0 else ""
                        for i in range(len(headers))
                    ]
                )

        except csv.Error:
            # Fallback to plain text display if CSV parsing fails
            self.add_column("Content")
            for line in self._content.split("\n")[: self._max_rows]:
                self.add_row(line)
