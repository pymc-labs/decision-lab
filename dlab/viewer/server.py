"""
FastAPI server for the session viewer.

Serves the HTML viewer and JSON API endpoints for session data,
artifacts, and work directory files.
"""

import importlib.resources
import mimetypes
import socket
import threading
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from dlab.viewer.layout import compute_process_layout
from dlab.viewer.session_data import extract_process_tree


def _create_app(work_dir: Path) -> FastAPI:
    """
    Create the FastAPI application for a session viewer.

    Parameters
    ----------
    work_dir : Path
        Resolved path to the session work directory.

    Returns
    -------
    FastAPI
        Configured application instance.
    """
    app: FastAPI = FastAPI(title="dlab session viewer")

    # Pre-compute session data and layout at startup
    session_data: dict[str, Any] = extract_process_tree(work_dir)
    layout_result: dict[str, Any] = compute_process_layout(session_data["tree"])

    # Load HTML template
    html_content: str = _load_viewer_html()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        """Serve the viewer HTML page."""
        return HTMLResponse(content=html_content)

    @app.get("/api/session")
    async def get_session() -> JSONResponse:
        """Return pre-computed session data with layout."""
        return JSONResponse(content={
            "session": session_data,
            "layout": layout_result,
        })

    @app.get("/api/artifacts/{node_id:path}")
    async def get_artifacts(node_id: str) -> JSONResponse:
        """Return artifact list for a specific node."""
        artifacts: list[dict[str, Any]] = session_data.get("artifacts", {}).get(node_id, [])
        return JSONResponse(content={
            "node_id": node_id,
            "artifacts": artifacts,
        })

    @app.get("/api/file/{file_path:path}")
    async def get_file(file_path: str) -> FileResponse:
        """
        Serve a file from the work directory.

        Validates that the resolved path is within work_dir
        to prevent directory traversal attacks.
        """
        # Decode the path
        requested: Path = work_dir / file_path
        resolved: Path = requested.resolve()

        # Safety: ensure path is within work_dir
        if not resolved.is_relative_to(work_dir.resolve()):
            raise HTTPException(status_code=403, detail="Access denied")

        if not resolved.exists() or not resolved.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        # Determine MIME type
        mime_type: str | None = mimetypes.guess_type(str(resolved))[0]
        if mime_type is None:
            mime_type = "application/octet-stream"

        return FileResponse(
            path=resolved,
            media_type=mime_type,
            filename=resolved.name,
        )

    return app


def _load_viewer_html() -> str:
    """
    Load the viewer HTML template from package data.

    Returns
    -------
    str
        HTML content.
    """
    html_package = importlib.resources.files("dlab.viewer.html")
    html_file = html_package.joinpath("viewer.html")
    return html_file.read_text(encoding="utf-8")


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_viewer(
    work_dir: Path,
    port: int = 0,
    open_browser: bool = True,
) -> int:
    """
    Start the viewer server and optionally open a browser.

    Parameters
    ----------
    work_dir : Path
        Resolved path to session work directory.
    port : int
        Port number. 0 = auto-select a free port.
    open_browser : bool
        Whether to open the default browser.

    Returns
    -------
    int
        Exit code (0 for success).
    """
    if port == 0:
        port = _find_free_port()

    app: FastAPI = _create_app(work_dir)
    url: str = f"http://127.0.0.1:{port}"

    print(f"dlab viewer: {work_dir.name}")
    print(f"  {url}")
    print(f"  Press Ctrl+C to stop")

    if open_browser:
        # Open browser after a short delay to let server start
        timer: threading.Timer = threading.Timer(0.8, webbrowser.open, args=[url])
        timer.daemon = True
        timer.start()

    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    except KeyboardInterrupt:
        pass

    return 0
