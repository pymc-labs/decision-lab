"""
Peer Review Library

Modules:
- parse_paper: PDF/LaTeX → structured text with section boundaries
- fetch_references: Semantic Scholar API client for building reference KB
"""

__version__ = "0.1.0"

from .parse_paper import parse_paper, parse_and_print
from .fetch_references import fetch_reference, fetch_references_batch

__all__ = [
    "__version__",
    "parse_paper",
    "parse_and_print",
    "fetch_reference",
    "fetch_references_batch",
]
