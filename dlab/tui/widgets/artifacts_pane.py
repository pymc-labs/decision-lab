"""
Artifact widgets for browsing and viewing agent output files.

Provides:
- ArtifactList: File list in left sidebar
- FileViewer: Scrollable file content viewer with image support
"""

import csv
import io
import re
from pathlib import Path

from textual.widgets import ListView, ListItem, Static, DataTable
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.console import Group


# File extensions to include as artifacts
ARTIFACT_EXTENSIONS = {".md", ".py", ".txt", ".csv", ".png", ".jpg", ".jpeg", ".pdf"}

# Directories to exclude from artifact discovery
EXCLUDE_DIRS = {".git", ".opencode", "_opencode_logs", "_docker", "_hooks", "node_modules", "__pycache__", "data"}

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


def discover_artifacts(
    work_dir: Path, agent_dir: Path | None, is_main: bool = False
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
    artifacts: list[Path] = []
    search_dir = agent_dir if agent_dir else work_dir

    if not search_dir.exists():
        return artifacts

    for path in search_dir.rglob("*"):
        if not path.is_file():
            continue

        # Skip excluded directories
        if any(excluded in path.parts for excluded in EXCLUDE_DIRS):
            continue

        # For main agent, skip files inside parallel run directories
        if is_main and any(is_parallel_run_dir(part) for part in path.parts):
            continue

        # Check extension
        if path.suffix.lower() not in ARTIFACT_EXTENSIONS:
            continue

        # Store relative path (relative to agent_dir for subagents, work_dir for main)
        base = agent_dir if agent_dir else work_dir
        try:
            rel_path = path.relative_to(base)
            artifacts.append(rel_path)
        except ValueError:
            artifacts.append(path)

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
            display_path = display_path[:max_len - 1] + "…"

        text = Text()
        text.append(f"{tag:>3}", style="dim")
        text.append(f" {display_path}")
        yield Static(text)


_ARTIFACT_TYPE_ORDER: dict[str, int] = {
    ".md": 0, ".py": 1,
    ".png": 2, ".jpg": 2, ".jpeg": 2,
    ".csv": 3,
}


def _sort_artifacts(artifacts: list[Path]) -> list[Path]:
    """Sort artifacts by type (md, py, img, csv, rest) then name."""
    return sorted(
        artifacts,
        key=lambda p: (_ARTIFACT_TYPE_ORDER.get(p.suffix.lower(), 99), p.name.lower()),
    )


class ArtifactList(ListView):
    """
    File list in left sidebar.

    Shows artifacts for selected agent with icons.
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
        self._artifacts: list[Path] = []
        self._agent_name: str | None = None

    def set_agent(self, agent_name: str | None) -> None:
        """Update artifacts for selected agent."""
        self._agent_name = agent_name

        # Get agent directory
        self._agent_dir = get_agent_directory(self._work_dir, agent_name)

        # Check if this is the main agent
        is_main = agent_name is not None and agent_name.startswith("main")

        # Discover artifacts
        self._artifacts = discover_artifacts(self._work_dir, self._agent_dir, is_main=is_main)

        # Rebuild list
        self.clear()

        if not self._artifacts:
            self.append(ListItem(Static(Text("No files", style="dim italic"))))
            return

        self._artifacts = _sort_artifacts(self._artifacts)

        for path in self._artifacts:
            self.append(ArtifactItem(path))

    def refresh_if_changed(self) -> None:
        """Re-discover artifacts and update list only if files changed."""
        if self._agent_name is None:
            return

        self._agent_dir = get_agent_directory(self._work_dir, self._agent_name)
        is_main = self._agent_name.startswith("main")
        new_artifacts = _sort_artifacts(discover_artifacts(self._work_dir, self._agent_dir, is_main=is_main))

        if new_artifacts != self._artifacts:
            self._artifacts = new_artifacts
            self.clear()
            if not self._artifacts:
                self.append(ListItem(Static(Text("No files", style="dim italic"))))
                return
            for path in self._artifacts:
                self.append(ArtifactItem(path))

    def _resolve_path(self, rel_path: Path) -> Path:
        """Resolve a relative artifact path to an absolute path."""
        base = self._agent_dir if self._agent_dir else self._work_dir
        return base / rel_path

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle selection (Enter key)."""
        if isinstance(event.item, ArtifactItem):
            self.post_message(self.FileSelected(self._resolve_path(event.item.file_path)))

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
        import subprocess
        import sys

        path = self.get_highlighted_path()
        if not path or not path.exists():
            return False

        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform == "win32":
            subprocess.Popen(["start", str(path)], shell=True)
        else:
            subprocess.Popen(["xdg-open", str(path)])

        return True


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
        import subprocess
        import sys

        if not self._file_path or not self._file_path.exists():
            return False

        # Open with system default viewer
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(self._file_path)])
        elif sys.platform == "win32":
            subprocess.Popen(["start", str(self._file_path)], shell=True)
        else:
            subprocess.Popen(["xdg-open", str(self._file_path)])

        return True


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
        import subprocess
        import sys

        if not self._path.exists():
            return

        if sys.platform == "darwin":
            subprocess.Popen(["open", str(self._path)])
        elif sys.platform == "win32":
            subprocess.Popen(["start", str(self._path)], shell=True)
        else:
            subprocess.Popen(["xdg-open", str(self._path)])


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
        import subprocess
        import sys

        if not self._path.exists():
            return

        if sys.platform == "darwin":
            subprocess.Popen(["open", str(self._path)])
        elif sys.platform == "win32":
            subprocess.Popen(["start", str(self._path)], shell=True)
        else:
            subprocess.Popen(["xdg-open", str(self._path)])


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
                self.add_row(*[f"... {truncated} more rows ..." if i == 0 else "" for i in range(len(headers))])

        except csv.Error:
            # Fallback to plain text display if CSV parsing fails
            self.add_column("Content")
            for line in self._content.split("\n")[: self._max_rows]:
                self.add_row(line)
