"""
Log file watcher using simple polling.

Tracks file positions and streams new log events as they are appended.
"""

import threading
from pathlib import Path
from queue import Queue
from typing import Any, Callable

from dlab.opencode_logparser import LogEvent as ParsedEvent, parse_line


class LogWatcher:
    """
    Watches log directory for changes via periodic polling.

    Simple and reliable approach - polls all log files for new content.
    Called periodically from the UI update timer.
    """

    def __init__(self, logs_dir: Path) -> None:
        """
        Initialize watcher.

        Parameters
        ----------
        logs_dir : Path
            Directory containing log files.
        """
        self._logs_dir = logs_dir
        self._event_queue: Queue[tuple[str, dict[str, Any]]] = Queue()
        self._file_positions: dict[Path, int] = {}
        self._file_inodes: dict[Path, int] = {}  # Track inode for replacement detection
        self._lock = threading.Lock()
        self._running = False

    def _get_source_name(self, log_path: Path) -> str:
        """
        Convert log path to source name.

        Parameters
        ----------
        log_path : Path
            Path to log file.

        Returns
        -------
        str
            Source name (e.g., "main", "instance-1").
        """
        try:
            rel_path = log_path.relative_to(self._logs_dir)
            if len(rel_path.parts) > 1:
                return f"{rel_path.parent.name}/{rel_path.stem}"
            return rel_path.stem
        except ValueError:
            return log_path.stem

    def _read_new_lines(self, log_path: Path) -> list[tuple[str, dict[str, Any]]]:
        """
        Read new lines from a log file.

        Handles atomic file replacement (common in Docker) by detecting:
        - File inode changed (new file with same name)
        - File size smaller than stored position (truncation)

        Parameters
        ----------
        log_path : Path
            Path to log file.

        Returns
        -------
        list[tuple[str, dict[str, Any]]]
            List of (source, event) tuples.
        """
        if not log_path.exists() or log_path.suffix != ".log":
            return []

        source = self._get_source_name(log_path)
        events: list[tuple[str, dict[str, Any]]] = []

        with self._lock:
            position = self._file_positions.get(log_path, 0)
            old_inode = self._file_inodes.get(log_path, 0)

            try:
                stat = log_path.stat()
                current_size = stat.st_size
                current_inode = stat.st_ino

                # Detect file replacement or truncation:
                # - Inode changed = file was atomically replaced (temp + rename)
                # - Size < position = file was truncated
                if current_inode != old_inode or current_size < position:
                    # File was replaced - start from beginning
                    position = 0

                with open(log_path, "r") as f:
                    f.seek(position)
                    new_content = f.read()
                    new_position = f.tell()

                self._file_positions[log_path] = new_position
                self._file_inodes[log_path] = current_inode

                # Track consecutive raw text lines to group them
                raw_text_lines: list[str] = []

                def flush_raw_text() -> None:
                    """Flush accumulated raw text lines as a single event."""
                    if raw_text_lines:
                        event = {
                            "type": "raw_text",
                            "timestamp": None,
                            "part": {"text": "\n".join(raw_text_lines)},
                        }
                        events.append((source, event))
                        raw_text_lines.clear()

                for line in new_content.splitlines():
                    parsed: ParsedEvent | None = parse_line(line)
                    if parsed is None:
                        continue

                    if parsed.event_type == "raw_text":
                        raw_text_lines.append(parsed.part.get("text", ""))
                    else:
                        flush_raw_text()
                        # Convert ParsedEvent back to dict for the existing queue interface
                        event: dict[str, Any] = {
                            "type": parsed.event_type,
                            "timestamp": parsed.timestamp,
                            "sessionID": parsed.session_id,
                            "part": parsed.part,
                        }
                        # Preserve full raw data for events that have it
                        if parsed.raw:
                            event = parsed.raw
                        events.append((source, event))

                # Flush any remaining raw text
                flush_raw_text()

            except (IOError, OSError):
                pass

        return events

    def start(self) -> None:
        """
        Start watching - reads all existing log files.
        """
        if self._running:
            return

        # Read existing content
        for log_path in self._logs_dir.rglob("*.log"):
            for source, event in self._read_new_lines(log_path):
                self._event_queue.put((source, event))

        self._running = True

    def stop(self) -> None:
        """Stop watching."""
        self._running = False

    def poll(self) -> None:
        """
        Poll all log files for new content.

        Should be called periodically from the UI update timer.
        """
        if not self._running:
            return

        for log_path in self._logs_dir.rglob("*.log"):
            for source, event in self._read_new_lines(log_path):
                self._event_queue.put((source, event))

    def get_events(self) -> list[tuple[str, dict[str, Any]]]:
        """
        Get all pending events from queue (non-blocking).

        Returns
        -------
        list[tuple[str, dict[str, Any]]]
            List of (source_name, event_dict) tuples.
        """
        events: list[tuple[str, dict[str, Any]]] = []
        while not self._event_queue.empty():
            try:
                events.append(self._event_queue.get_nowait())
            except Exception:
                break
        return events

    @property
    def is_running(self) -> bool:
        """Whether watcher is currently running."""
        return self._running
