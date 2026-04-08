"""
FastAPI server and HTML export for the session viewer.

Serves the HTML viewer and JSON API endpoints for session data,
artifacts, and work directory files. Also supports exporting a
self-contained HTML file with all data and artifacts inlined.
"""

import base64
import importlib.resources
import json
import mimetypes
import socket
import threading
import webbrowser
from pathlib import Path
from typing import Any

from dlab.viewer.layout import compute_process_layout
from dlab.viewer.session_data import extract_process_tree


def _create_app(work_dir: Path) -> "FastAPI":
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
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

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
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    except KeyboardInterrupt:
        pass

    return 0


def _collect_artifacts(
    work_dir: Path,
    session_data: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """
    Collect all artifact files from the session tree as inline data.

    Binary files (images) are base64-encoded as data URIs.
    Text files are stored as raw strings.

    Parameters
    ----------
    work_dir : Path
        Session work directory.
    session_data : dict[str, Any]
        Session data from extract_process_tree().

    Returns
    -------
    dict[str, dict[str, str]]
        Map of file path → {"content": str, "type": "text"|"base64", "mime": str}.
    """
    artifact_map: dict[str, dict[str, str]] = {}

    def _walk_artifacts(tree: dict[str, Any]) -> None:
        for art in tree.get("artifacts", []):
            path_str: str = art["path"]
            if path_str in artifact_map:
                continue
            file_path: Path = work_dir / path_str
            if not file_path.exists():
                continue

            mime: str = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            if mime.startswith("text/") or mime in ("application/json",) or file_path.suffix in (".md", ".py", ".txt", ".csv"):
                try:
                    content: str = file_path.read_text(encoding="utf-8", errors="replace")
                    # Truncate large CSV files
                    if file_path.suffix == ".csv":
                        lines: list[str] = content.split("\n")
                        if len(lines) > CSV_MAX_ROWS + 1:  # +1 for header
                            content = "\n".join(lines[:CSV_MAX_ROWS + 1])
                            content += f"\n\n... truncated ({len(lines) - 1} rows total, showing {CSV_MAX_ROWS})"
                    artifact_map[path_str] = {"content": content, "type": "text", "mime": mime}
                except Exception:
                    pass
            else:
                try:
                    raw: bytes = file_path.read_bytes()
                    b64: str = base64.b64encode(raw).decode("ascii")
                    artifact_map[path_str] = {"content": f"data:{mime};base64,{b64}", "type": "base64", "mime": mime}
                except Exception:
                    pass

        # Recurse into child sessions
        for todo in tree.get("todos", []):
            for turn in todo.get("turns", []):
                if turn.get("type") == "parallel":
                    for child in turn.get("children", []):
                        _walk_artifacts(child)
                    cons = turn.get("consolidator")
                    if cons:
                        _walk_artifacts(cons)
        for turn in tree.get("preamble_turns", []):
            if turn.get("type") == "parallel":
                for child in turn.get("children", []):
                    _walk_artifacts(child)

    _walk_artifacts(session_data["tree"])
    return artifact_map


CDN_SCRIPTS: list[str] = [
    "https://d3js.org/d3.v7.min.js",
    "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/python.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/bash.min.js",
]

CDN_CSS: list[str] = [
    "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css",
]


def _inline_cdn_resources(html: str) -> str:
    """
    Try to download CDN scripts/CSS and inline them.

    If download fails, leave the CDN URLs in place.

    Parameters
    ----------
    html : str
        HTML content with CDN script/link tags.

    Returns
    -------
    str
        HTML with inlined resources where possible.
    """
    import urllib.request
    import urllib.error

    for url in CDN_SCRIPTS:
        tag: str = f'<script src="{url}"></script>'
        if tag not in html:
            continue
        try:
            req: urllib.request.Request = urllib.request.Request(url, headers={"User-Agent": "dlab-viewer/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                content: str = resp.read().decode("utf-8")
            html = html.replace(tag, f"<script>{content}</script>")
        except (urllib.error.URLError, OSError, TimeoutError):
            pass  # keep CDN URL as fallback

    for url in CDN_CSS:
        tag = f'<link rel="stylesheet" href="{url}">'
        if tag not in html:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dlab-viewer/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode("utf-8")
            html = html.replace(tag, f"<style>{content}</style>")
        except (urllib.error.URLError, OSError, TimeoutError):
            pass

    return html


CSV_MAX_ROWS: int = 1000


def export_viewer(work_dir: Path, output_path: Path) -> int:
    """
    Export a self-contained HTML viewer file.

    All session data and artifact files are inlined into the HTML.
    The resulting file can be opened in any browser without a server.

    Parameters
    ----------
    work_dir : Path
        Session work directory.
    output_path : Path
        Output HTML file path.

    Returns
    -------
    int
        Exit code (0 for success).
    """
    session_data: dict[str, Any] = extract_process_tree(work_dir)
    layout_result: dict[str, Any] = compute_process_layout(session_data["tree"])

    # Collect all artifacts as inline data
    print(f"Collecting artifacts...")
    artifact_map: dict[str, dict[str, str]] = _collect_artifacts(work_dir, session_data)
    print(f"  {len(artifact_map)} files collected")

    # Build the inline data payload
    payload: dict[str, Any] = {
        "session": session_data,
        "layout": layout_result,
    }

    html_template: str = _load_viewer_html()

    # Inject inline data and artifact map into the HTML.
    # Replace the fetch-based init() with inline data.
    inject_script: str = f"""
<script>
// Inline session data (exported mode — no server needed)
window.__INLINE_DATA__ = {json.dumps(payload)};
window.__ARTIFACT_MAP__ = {json.dumps(artifact_map)};
</script>"""

    # Insert before the closing </head>
    html: str = html_template.replace("</head>", inject_script + "\n</head>")

    # Patch the init() function to use inline data instead of fetch
    html = html.replace(
        "const res = await fetch('/api/session');\n  const data = await res.json();",
        "const data = window.__INLINE_DATA__;",
    )

    # Patch artifact loading to use the inline map
    # Replace fetch-based file loading with map lookup
    artifact_loader: str = """
// Patched for export mode: load from inline artifact map
async function loadArtifactFromMap(path) {
  const map = window.__ARTIFACT_MAP__ || {};
  const entry = map[path];
  if (!entry) return { text: null, isDataUri: false };
  if (entry.type === 'base64') return { text: entry.content, isDataUri: true };
  return { text: entry.content, isDataUri: false };
}"""

    html = html.replace(
        "async function loadArtifact(idx) {",
        artifact_loader + "\nasync function loadArtifact(idx) {",
    )

    # Patch the image src and fetch calls inside loadArtifact
    html = html.replace(
        """if (a.type === 'image') {
    viewer.innerHTML = `<img src="/api/file/${a.path.split('/').map(encodeURIComponent).join('/')}"/>`;
    return;
  }
  try {
    const res = await fetch(`/api/file/${a.path.split('/').map(encodeURIComponent).join('/')}`);
    const text = await res.text();""",
        """const artData = await loadArtifactFromMap(a.path);
  if (a.type === 'image') {
    if (artData.isDataUri) {
      viewer.innerHTML = `<img src="${artData.text}"/>`;
    } else {
      viewer.innerHTML = '<pre style="color:var(--text-tertiary)">Image not available</pre>';
    }
    return;
  }
  try {
    const text = artData.text;
    if (!text) throw new Error('File not found in export');""",
    )

    # Inline CDN scripts/CSS for fully offline use
    print("Inlining JS/CSS libraries...")
    html = _inline_cdn_resources(html)

    output_path.write_text(html, encoding="utf-8")

    total_size: float = len(html) / (1024 * 1024)
    print(f"Exported to {output_path} ({total_size:.1f} MB)")
    return 0
