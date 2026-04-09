"""
Paper parsing module for PDF and LaTeX inputs.

Extracts structured text, section boundaries, citations, and metadata
from academic papers in either PDF or LaTeX format.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def _detect_format(path: str | Path) -> str:
    """
    Detect whether a file is PDF or LaTeX.

    Checks the file extension first; for ambiguous cases falls back to
    reading the first few magic bytes of the file.

    Parameters
    ----------
    path : str | Path
        Filesystem path to the paper file.

    Returns
    -------
    str
        ``"pdf"`` or ``"latex"``.

    Raises
    ------
    ValueError
        If the format cannot be determined.
    """
    p = Path(path)
    ext = p.suffix.lower()

    if ext == ".pdf":
        return "pdf"
    if ext in {".tex", ".latex"}:
        return "latex"

    # Fall back to magic bytes
    try:
        with open(p, "rb") as fh:
            header = fh.read(8)
        if header.startswith(b"%PDF"):
            return "pdf"
        # LaTeX files typically start with a comment or \documentclass
        try:
            snippet = header.decode("utf-8", errors="replace")
            if snippet.lstrip().startswith(("\\", "%")):
                return "latex"
        except Exception:
            pass
    except OSError:
        pass

    raise ValueError(
        f"Cannot determine format for '{path}'. "
        "Provide a .pdf or .tex file."
    )


# ---------------------------------------------------------------------------
# Section / citation helpers
# ---------------------------------------------------------------------------

# Regex patterns for section headings in plain text (PDF-extracted or LaTeX)
_SECTION_PATTERNS: list[re.Pattern[str]] = [
    # "Abstract" / "ABSTRACT" on its own line
    re.compile(r"^(Abstract|ABSTRACT)\s*$", re.MULTILINE),
    # Numbered: "1. Introduction", "1 Introduction", "2.1 Related Work"
    re.compile(
        r"^(\d+(?:\.\d+)*\.?\s+[A-Z][^\n]{2,60})\s*$",
        re.MULTILINE,
    ),
    # ALL CAPS headings (2+ words or single word ≥5 chars)
    re.compile(
        r"^([A-Z][A-Z\s\-]{4,60}[A-Z])\s*$",
        re.MULTILINE,
    ),
]

# Citation patterns for plain text
_CITATION_PATTERNS: list[re.Pattern[str]] = [
    # Bracketed numeric: [1], [2,3], [2, 3, 4]
    re.compile(r"\[(\d+(?:,\s*\d+)*)\]"),
    # Author-year in brackets: [Smith et al., 2023] or [Smith, 2023]
    re.compile(r"\[([A-Z][a-zA-Z\-]+(?:\s+et\s+al\.)?,\s*\d{4}(?:;\s*[A-Z][a-zA-Z\-]+(?:\s+et\s+al\.)?,\s*\d{4})*)\]"),
    # Parenthetical: (Smith, 2023) or (Smith & Jones, 2023)
    re.compile(r"\(([A-Z][a-zA-Z\-]+(?:\s*&\s*[A-Z][a-zA-Z\-]+)?,\s*\d{4})\)"),
]

# LaTeX citation commands
_LATEX_CITE_PATTERN: re.Pattern[str] = re.compile(
    r"\\cite[pt]?\*?\{([^}]+)\}"
)


def _extract_sections_from_text(text: str) -> list[dict[str, str]]:
    """
    Detect section headings in plain text and split into sections.

    Recognises three heading styles: "Abstract"/"ABSTRACT", numbered
    headings like "1. Introduction" or "2.1 Related Work", and ALL-CAPS
    headings such as "INTRODUCTION".

    Parameters
    ----------
    text : str
        Plain text content of the paper.

    Returns
    -------
    list[dict[str, str]]
        List of dicts, each with keys ``"heading"`` and ``"text"``.
        The text is the content that follows the heading up to the next
        heading (or end of document).
    """
    # Collect all (position, heading_text) matches, deduplicated by position
    matches: list[tuple[int, str]] = []
    seen_positions: set[int] = set()

    for pattern in _SECTION_PATTERNS:
        for m in pattern.finditer(text):
            pos = m.start()
            if pos not in seen_positions:
                seen_positions.add(pos)
                matches.append((pos, m.group(0).strip()))

    # Sort by position in document
    matches.sort(key=lambda x: x[0])

    if not matches:
        # No headings found — return the whole text as a single unnamed section
        return [{"heading": "", "text": text.strip()}]

    sections: list[dict[str, str]] = []

    # Content before first heading (often title / author block)
    if matches[0][0] > 0:
        pre_text = text[: matches[0][0]].strip()
        if pre_text:
            sections.append({"heading": "PREAMBLE", "text": pre_text})

    for i, (pos, heading) in enumerate(matches):
        # Find where this section's body ends (start of next heading or EOF)
        if i + 1 < len(matches):
            end_pos = matches[i + 1][0]
        else:
            end_pos = len(text)

        # Body starts after the heading line
        body_start = pos + len(heading)
        body = text[body_start:end_pos].strip()
        sections.append({"heading": heading, "text": body})

    return sections


def _extract_citations(text: str) -> list[str]:
    """
    Extract citation references from plain text.

    Handles bracketed numeric citations ``[1]``, author-year brackets
    ``[Smith et al., 2023]``, and parenthetical forms ``(Smith, 2023)``.

    Parameters
    ----------
    text : str
        Plain text content of the paper.

    Returns
    -------
    list[str]
        Sorted, deduplicated list of citation strings.
    """
    citations: set[str] = set()

    for pattern in _CITATION_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group(0)
            # Split compound bracketed numbers: [2, 3, 4] → "[2]", "[3]", "[4]"
            inner = m.group(1)
            if re.fullmatch(r"\d+(?:,\s*\d+)*", inner):
                for num in re.split(r",\s*", inner):
                    citations.add(f"[{num.strip()}]")
            else:
                citations.add(raw.strip())

    return sorted(citations)


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def _parse_pdf(path: str | Path) -> dict[str, Any]:
    """
    Parse a PDF file using PyMuPDF.

    Extracts the full text, attempts to infer a title from the first page,
    counts pages, detects figures, splits into sections, and extracts
    citation references.

    Parameters
    ----------
    path : str | Path
        Path to the PDF file.

    Returns
    -------
    dict[str, Any]
        Keys: ``title``, ``pages``, ``source``, ``figures_detected``,
        ``citations``, ``sections``, ``full_text``.
    """
    import fitz  # PyMuPDF — available inside Docker only

    doc = fitz.open(str(path))
    pages: int = doc.page_count

    page_texts: list[str] = []
    figures_detected: int = 0

    for page in doc:
        page_texts.append(page.get_text())
        # Count image objects on the page as a proxy for figures
        image_list = page.get_images(full=False)
        figures_detected += len(image_list)

    doc.close()

    full_text: str = "\n".join(page_texts)

    # Heuristic: title is the first non-empty line of the first page
    title: str = ""
    for line in page_texts[0].splitlines():
        stripped = line.strip()
        if stripped:
            title = stripped
            break

    sections = _extract_sections_from_text(full_text)
    citations = _extract_citations(full_text)

    return {
        "title": title,
        "pages": pages,
        "source": "PDF",
        "figures_detected": figures_detected,
        "citations": citations,
        "sections": sections,
        "full_text": full_text,
    }


# ---------------------------------------------------------------------------
# LaTeX parsing
# ---------------------------------------------------------------------------

# Patterns for LaTeX structure
_LATEX_SECTION_PATTERN: re.Pattern[str] = re.compile(
    r"\\(section|subsection|subsubsection)\*?\{([^}]+)\}"
)
_LATEX_ABSTRACT_PATTERN: re.Pattern[str] = re.compile(
    r"\\begin\{abstract\}(.*?)\\end\{abstract\}",
    re.DOTALL,
)
_LATEX_TITLE_PATTERN: re.Pattern[str] = re.compile(
    r"\\title\*?\{([^}]+)\}"
)
_LATEX_FIGURE_PATTERN: re.Pattern[str] = re.compile(
    r"\\begin\{figure"
)
# Strip LaTeX commands for body text extraction
_LATEX_COMMAND_PATTERN: re.Pattern[str] = re.compile(
    r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^}]*)\}|\\[a-zA-Z]+"
)
_LATEX_COMMENT_PATTERN: re.Pattern[str] = re.compile(r"%.*$", re.MULTILINE)


def _latex_to_plain(text: str) -> str:
    """
    Convert LaTeX source to approximate plain text.

    Strips comments and common commands while preserving the inner
    text of brace groups.

    Parameters
    ----------
    text : str
        Raw LaTeX source.

    Returns
    -------
    str
        Approximate plain text.
    """
    # Remove comments
    text = _LATEX_COMMENT_PATTERN.sub("", text)
    # Expand commands: keep the content inside braces
    text = _LATEX_COMMAND_PATTERN.sub(lambda m: m.group(1) or "", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_latex(path: str | Path) -> dict[str, Any]:
    """
    Parse a LaTeX ``.tex`` file.

    Reads the raw source and extracts: title (from ``\\title{}``),
    abstract (from ``\\begin{abstract}``), sections (from ``\\section{}``
    and ``\\subsection{}``), figures (count of ``\\begin{figure}``
    environments), and citations (from ``\\cite{}``, ``\\citep{}``,
    ``\\citet{}``).

    Parameters
    ----------
    path : str | Path
        Path to the ``.tex`` file.

    Returns
    -------
    dict[str, Any]
        Keys: ``title``, ``pages``, ``source``, ``figures_detected``,
        ``citations``, ``sections``, ``full_text``.
    """
    raw: str = Path(path).read_text(encoding="utf-8", errors="replace")

    # Title
    title_match = _LATEX_TITLE_PATTERN.search(raw)
    title: str = title_match.group(1).strip() if title_match else ""

    # Figures (count environments)
    figures_detected: int = len(_LATEX_FIGURE_PATTERN.findall(raw))

    # Citations
    citation_keys: set[str] = set()
    for m in _LATEX_CITE_PATTERN.finditer(raw):
        for key in m.group(1).split(","):
            citation_keys.add(key.strip())
    citations: list[str] = sorted(citation_keys)

    # Sections — build list of (position, label, heading_text)
    section_markers: list[tuple[int, str, str]] = []

    abstract_match = _LATEX_ABSTRACT_PATTERN.search(raw)
    if abstract_match:
        section_markers.append((abstract_match.start(), "abstract", "Abstract"))

    for m in _LATEX_SECTION_PATTERN.finditer(raw):
        level = m.group(1)          # "section", "subsection", etc.
        heading_text = m.group(2).strip()
        label = f"{level}:{heading_text}"
        section_markers.append((m.start(), label, heading_text))

    section_markers.sort(key=lambda x: x[0])

    sections: list[dict[str, str]] = []

    if abstract_match:
        abstract_body = _latex_to_plain(abstract_match.group(1))
        sections.append({"heading": "Abstract", "text": abstract_body})

    # Build a lookup from position to abstract so we can skip it below
    abstract_pos: int = abstract_match.start() if abstract_match else -1

    non_abstract_markers = [
        (pos, label, htxt)
        for pos, label, htxt in section_markers
        if pos != abstract_pos
    ]

    for i, (pos, _label, heading_text) in enumerate(non_abstract_markers):
        # Body of this section = source from end of \section{…} to next marker
        section_cmd_end = raw.index("}", pos) + 1
        if i + 1 < len(non_abstract_markers):
            body_end = non_abstract_markers[i + 1][0]
        else:
            body_end = len(raw)
        body_raw = raw[section_cmd_end:body_end]
        body = _latex_to_plain(body_raw)
        sections.append({"heading": heading_text, "text": body})

    full_text: str = _latex_to_plain(raw)

    return {
        "title": title,
        "pages": 0,          # Page count not meaningful for LaTeX source
        "source": "LaTeX",
        "figures_detected": figures_detected,
        "citations": citations,
        "sections": sections,
        "full_text": full_text,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_paper(path: str | Path) -> dict[str, Any]:
    """
    Parse an academic paper from PDF or LaTeX source.

    Detects the input format automatically, then delegates to the
    appropriate parser. Returns a uniform dict regardless of source format.

    Parameters
    ----------
    path : str | Path
        Path to the paper file (``.pdf`` or ``.tex``).

    Returns
    -------
    dict[str, Any]
        Dictionary with the following keys:

        title : str
            Inferred title (first text line for PDF; ``\\title{}`` for LaTeX).
        pages : int
            Number of pages (0 for LaTeX source).
        source : str
            ``"PDF"`` or ``"LaTeX"``.
        figures_detected : int
            Number of figures detected.
        citations : list[str]
            Sorted, deduplicated citation references.
        sections : list[dict[str, str]]
            List of ``{"heading": ..., "text": ...}`` dicts.
        full_text : str
            Full plain-text content.
    """
    fmt = _detect_format(path)
    if fmt == "pdf":
        return _parse_pdf(path)
    return _parse_latex(path)


def parse_and_print(path: str | Path) -> None:
    """
    Parse a paper and print structured output to stdout.

    This is the entry point called by the TypeScript tool. The output
    uses labelled section blocks so the calling process can parse it
    without needing to understand the underlying file format.

    Output format::

        === METADATA ===
        Title: ...
        Pages: ...
        Source: PDF | LaTeX
        Figures detected: ...
        Citations found: N
        Citation keys: ["key1", "key2", ...]

        === ABSTRACT ===
        ...

        === 1. INTRODUCTION ===
        ...

    Parameters
    ----------
    path : str | Path
        Path to the paper file (``.pdf`` or ``.tex``).
    """
    result: dict[str, Any] = parse_paper(path)

    lines: list[str] = []

    # Metadata block
    lines.append("=== METADATA ===")
    lines.append(f"Title: {result['title']}")
    lines.append(f"Pages: {result['pages']}")
    lines.append(f"Source: {result['source']}")
    lines.append(f"Figures detected: {result['figures_detected']}")
    citations: list[str] = result["citations"]
    lines.append(f"Citations found: {len(citations)}")
    lines.append(f"Citation keys: {json.dumps(citations)}")

    # Section blocks
    sections: list[dict[str, str]] = result["sections"]

    # Separate abstract from the rest for ordering
    abstract_sections = [s for s in sections if s["heading"].lower() in {"abstract", ""}]
    other_sections = [s for s in sections if s["heading"].lower() not in {"abstract", ""}]

    for section in abstract_sections:
        heading = section["heading"] or "ABSTRACT"
        lines.append("")
        lines.append(f"=== {heading.upper()} ===")
        lines.append(section["text"])

    for i, section in enumerate(other_sections, start=1):
        heading = section["heading"]
        # If the heading already starts with a number, use it as-is;
        # otherwise prefix with an index.
        if re.match(r"^\d", heading):
            label = heading.upper()
        else:
            label = f"{i}. {heading.upper()}"
        lines.append("")
        lines.append(f"=== {label} ===")
        lines.append(section["text"])

    print("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <paper.pdf|paper.tex>", file=sys.stderr)
        sys.exit(1)
    parse_and_print(sys.argv[1])
